from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from cache import get_cache, set_cache
from crud import fetch_latest_activity
from database import engine, get_db
from models import AIInsight, BankAccount, Budget, Category, ExpenseNew, Income, SavingsGoal, Transaction, User
from oauth2 import get_current_user
from services.calculation_service import goalProgress, requiredMonthlySavings

router = APIRouter()


def _to_decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def _serialize_money(value) -> float:
    return float(_to_decimal(value).quantize(Decimal("0.01")))


def _month_bucket(column):
    if engine.dialect.name == "postgresql":
        return func.to_char(column, "YYYY-MM")
    return func.strftime("%Y-%m", column)


def _current_period_range(period: str = "monthly") -> tuple[date, date]:
    today = date.today()
    if period == "weekly":
        first_day = today - timedelta(days=today.weekday())
        return first_day, first_day + timedelta(days=7)

    first_day = today.replace(day=1)
    if today.month == 12:
        return first_day, today.replace(year=today.year + 1, month=1, day=1)
    return first_day, today.replace(month=today.month + 1, day=1)


def _aggregate_transaction_totals(
    db: Session,
    user_id: int,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> tuple[Decimal, Decimal]:
    query = db.query(
        func.coalesce(func.sum(case((Transaction.amount > 0, Transaction.amount), else_=0)), 0).label("income"),
        func.coalesce(func.sum(case((Transaction.amount < 0, -Transaction.amount), else_=0)), 0).label("expenses"),
    ).filter(Transaction.user_id == user_id)

    if start is not None:
        query = query.filter(Transaction.date >= start)
    if end is not None:
        query = query.filter(Transaction.date < end)

    row = query.one()
    return _to_decimal(row.income), _to_decimal(row.expenses)


def _period_spending_maps(
    db: Session,
    user_id: int,
    period: str,
) -> tuple[dict[int, Decimal], dict[str, Decimal]]:
    first_day, last_day = _current_period_range(period)

    legacy_rows = (
        db.query(
            ExpenseNew.category_id,
            func.coalesce(func.sum(ExpenseNew.amount), 0).label("total"),
        )
        .filter(
            ExpenseNew.user_id == user_id,
            ExpenseNew.date >= first_day,
            ExpenseNew.date < last_day,
        )
        .group_by(ExpenseNew.category_id)
        .all()
    )
    legacy_map = {row.category_id: _to_decimal(row.total) for row in legacy_rows}

    transaction_rows = (
        db.query(
            Transaction.category.label("category"),
            func.coalesce(func.sum(-Transaction.amount), 0).label("total"),
        )
        .filter(
            Transaction.user_id == user_id,
            Transaction.amount < 0,
            Transaction.date >= first_day,
            Transaction.date < last_day,
        )
        .group_by(Transaction.category)
        .all()
    )
    transaction_map = {(row.category or "Uncategorized"): _to_decimal(row.total) for row in transaction_rows}
    return legacy_map, transaction_map


def _serialize_goal(goal: SavingsGoal) -> dict:
    if goal.target_date:
        today = date.today()
        months_remaining = max((goal.target_date.year - today.year) * 12 + (goal.target_date.month - today.month), 1)
    else:
        months_remaining = 0

    return {
        "id": goal.id,
        "name": goal.name,
        "targetAmount": _serialize_money(goal.target_amount),
        "currentAmount": _serialize_money(goal.current_amount),
        "currency": goal.currency,
        "country": goal.country,
        "targetDate": goal.target_date.isoformat() if goal.target_date else None,
        "progressPercentage": float(goalProgress(goal.current_amount, goal.target_amount)),
        "requiredMonthlySavings": float(requiredMonthlySavings(goal.target_amount, goal.current_amount, months_remaining))
        if months_remaining
        else 0,
        "createdAt": goal.created_at.isoformat() if goal.created_at else None,
    }


def _build_budget_payloads(
    db: Session,
    user_id: int,
    budgets: list[Budget],
) -> tuple[list[dict], list[dict]]:
    spending_by_period: dict[str, tuple[dict[int, Decimal], dict[str, Decimal]]] = {}
    budget_payloads: list[dict] = []
    warnings: list[dict] = []

    for budget in budgets:
        if budget.period not in spending_by_period:
            spending_by_period[budget.period] = _period_spending_maps(db, user_id, budget.period)

        legacy_map, transaction_map = spending_by_period[budget.period]
        category_name = budget.category.name if budget.category else "Uncategorized"
        spent = legacy_map.get(budget.category_id, Decimal("0.00")) + transaction_map.get(category_name, Decimal("0.00"))
        limit_amount = _to_decimal(budget.monthly_limit)
        remaining = max(limit_amount - spent, Decimal("0.00"))
        percentage = float((spent / limit_amount * Decimal("100")) if limit_amount > 0 else 0)
        status = "safe"
        if percentage >= 100:
            status = "exceeded"
        elif percentage >= 80:
            status = "warning"

        budget_payloads.append(
            {
                "id": budget.id,
                "category_id": budget.category_id,
                "category_name": category_name,
                "monthly_limit": _serialize_money(limit_amount),
                "period": budget.period,
                "currency": budget.currency,
                "country": budget.country,
                "spent": _serialize_money(spent),
                "remaining": _serialize_money(remaining),
                "percentage": round(percentage, 1),
                "status": status,
            }
        )

        if percentage >= 80:
            warnings.append(
                {
                    "budgetId": budget.id,
                    "category": category_name,
                    "status": "exceeded" if percentage >= 100 else "warning",
                    "percentage": round(percentage, 1),
                    "spent": _serialize_money(spent),
                    "limit": _serialize_money(limit_amount),
                }
            )

    return budget_payloads, warnings


def _build_dashboard_overview(current_user: User, db: Session) -> Dict:
    month_start, next_month_start = _current_period_range("monthly")

    total_income = (
        db.query(func.coalesce(func.sum(Income.amount), 0))
        .filter(Income.user_id == current_user.id)
        .scalar()
    )
    total_expenses = (
        db.query(func.coalesce(func.sum(ExpenseNew.amount), 0))
        .filter(ExpenseNew.user_id == current_user.id)
        .scalar()
    )
    monthly_income = (
        db.query(func.coalesce(func.sum(Income.amount), 0))
        .filter(Income.user_id == current_user.id, Income.date >= month_start, Income.date < next_month_start)
        .scalar()
    )
    monthly_expenses = (
        db.query(func.coalesce(func.sum(ExpenseNew.amount), 0))
        .filter(ExpenseNew.user_id == current_user.id, ExpenseNew.date >= month_start, ExpenseNew.date < next_month_start)
        .scalar()
    )

    transaction_income_total, transaction_expense_total = _aggregate_transaction_totals(db, current_user.id)
    transaction_income_month, transaction_expense_month = _aggregate_transaction_totals(
        db,
        current_user.id,
        start=month_start,
        end=next_month_start,
    )

    monthly_income_total = _to_decimal(monthly_income) + transaction_income_month
    monthly_expense_total = _to_decimal(monthly_expenses) + transaction_expense_month
    monthly_savings = monthly_income_total - monthly_expense_total
    savings_rate = float((monthly_savings / monthly_income_total * Decimal("100")) if monthly_income_total > 0 else 0)

    total_balance = (
        db.query(func.coalesce(func.sum(BankAccount.balance), 0))
        .filter(BankAccount.user_id == current_user.id, BankAccount.status == "active")
        .scalar()
    )

    income_month_bucket = _month_bucket(Income.date)
    expense_month_bucket = _month_bucket(ExpenseNew.date)

    income_trend_rows = (
        db.query(
            income_month_bucket.label("month"),
            func.coalesce(func.sum(Income.amount), 0).label("total"),
        )
        .filter(Income.user_id == current_user.id)
        .group_by(income_month_bucket)
        .order_by(income_month_bucket)
        .all()
    )
    expense_trend_rows = (
        db.query(
            expense_month_bucket.label("month"),
            func.coalesce(func.sum(ExpenseNew.amount), 0).label("total"),
        )
        .filter(ExpenseNew.user_id == current_user.id)
        .group_by(expense_month_bucket)
        .order_by(expense_month_bucket)
        .all()
    )

    income_by_month = {row.month: _serialize_money(row.total) for row in income_trend_rows}
    expense_by_month = {row.month: _serialize_money(row.total) for row in expense_trend_rows}
    legacy_months = sorted(set(income_by_month) | set(expense_by_month))

    savings_by_month = [income_by_month.get(month, 0.0) - expense_by_month.get(month, 0.0) for month in legacy_months]
    if len(savings_by_month) >= 3:
        x_values = list(range(len(savings_by_month)))
        count = len(x_values)
        sum_x = sum(x_values)
        sum_y = sum(savings_by_month)
        sum_xy = sum(x_values[index] * savings_by_month[index] for index in range(count))
        sum_x2 = sum(index * index for index in x_values)
        denominator = count * sum_x2 - sum_x * sum_x
        if denominator == 0:
            forecast = round(sum(savings_by_month) / count, 2)
        else:
            slope = (count * sum_xy - sum_x * sum_y) / denominator
            intercept = (sum_y - slope * sum_x) / count
            forecast = round(slope * len(savings_by_month) + intercept, 2)
    else:
        forecast = round(sum(savings_by_month) / len(savings_by_month), 2) if savings_by_month else 0.0

    category_rows = (
        db.query(
            Category.name.label("category"),
            func.sum(ExpenseNew.amount).label("total"),
        )
        .join(Category, ExpenseNew.category_id == Category.id)
        .filter(ExpenseNew.user_id == current_user.id)
        .group_by(Category.name)
        .order_by(Category.name)
        .all()
    )

    recent_activity = fetch_latest_activity(db, current_user, limit=12)
    unified_rows = (
        db.query(Transaction)
        .filter(Transaction.user_id == current_user.id)
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .limit(12)
        .all()
    )
    recent_activity.extend(
        [
            {
                "id": row.id,
                "transaction_type": row.type,
                "date": row.date.isoformat(),
                "amount": abs(float(row.amount)),
                "primary_label": row.merchant or row.category,
                "secondary_label": row.subcategory or row.source,
                "description": row.description,
                "payment_method": row.payment_method,
                "source": row.source,
            }
            for row in unified_rows
        ]
    )
    recent_activity.sort(key=lambda item: (item["date"] or "", str(item["id"])), reverse=True)

    budgets = (
        db.query(Budget)
        .options(joinedload(Budget.category))
        .filter(Budget.user_id == current_user.id)
        .order_by(Budget.created_at)
        .all()
    )
    budget_payloads, budget_warnings = _build_budget_payloads(db, current_user.id, budgets)

    ai_insights = [
        {"id": row.id, "title": row.title, "summary": row.summary, "type": row.insight_type}
        for row in db.query(AIInsight)
        .filter(AIInsight.user_id == current_user.id)
        .order_by(AIInsight.created_at.desc())
        .limit(3)
        .all()
    ]

    transaction_month_bucket = _month_bucket(Transaction.date)
    trend_rows = (
        db.query(
            transaction_month_bucket.label("month"),
            func.coalesce(func.sum(case((Transaction.amount > 0, Transaction.amount), else_=0)), 0).label("income"),
            func.coalesce(func.sum(case((Transaction.amount < 0, -Transaction.amount), else_=0)), 0).label("expenses"),
        )
        .filter(Transaction.user_id == current_user.id)
        .group_by(transaction_month_bucket)
        .order_by(transaction_month_bucket)
        .all()
    )
    trends = [
        {
            "month": row.month,
            "income": _serialize_money(row.income),
            "expenses": _serialize_money(row.expenses),
            "savings": _serialize_money(_to_decimal(row.income) - _to_decimal(row.expenses)),
        }
        for row in trend_rows
    ]

    current_month_category_rows = (
        db.query(
            Transaction.category.label("category"),
            func.coalesce(func.sum(-Transaction.amount), 0).label("total"),
        )
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.amount < 0,
            Transaction.date >= month_start,
            Transaction.date < next_month_start,
        )
        .group_by(Transaction.category)
        .order_by(func.sum(-Transaction.amount).desc())
        .all()
    )
    current_month_merchant_rows = (
        db.query(
            func.coalesce(Transaction.merchant, "Unknown").label("merchant"),
            func.coalesce(func.sum(-Transaction.amount), 0).label("total"),
        )
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.amount < 0,
            Transaction.date >= month_start,
            Transaction.date < next_month_start,
        )
        .group_by(func.coalesce(Transaction.merchant, "Unknown"))
        .order_by(func.sum(-Transaction.amount).desc())
        .limit(5)
        .all()
    )

    goals = (
        db.query(SavingsGoal)
        .filter(SavingsGoal.user_id == current_user.id)
        .order_by(SavingsGoal.created_at.desc())
        .all()
    )
    categories = (
        db.query(Category.id, Category.name)
        .order_by(Category.name.asc())
        .all()
    )

    dashboard_payload = {
        "summary": {
            "total_income": _serialize_money(_to_decimal(total_income) + transaction_income_total),
            "total_expenses": _serialize_money(_to_decimal(total_expenses) + transaction_expense_total),
            "net_balance": _serialize_money(
                _to_decimal(total_income) + transaction_income_total - _to_decimal(total_expenses) - transaction_expense_total
            ),
            "total_balance": _serialize_money(total_balance),
            "monthly_income": _serialize_money(monthly_income_total),
            "monthly_expenses": _serialize_money(monthly_expense_total),
            "monthly_savings": _serialize_money(monthly_savings),
            "savings_rate": round(savings_rate, 2),
            "forecast_next_month": forecast,
        },
        "income_vs_expenses": [
            {
                "month": month,
                "income": income_by_month.get(month, 0.0),
                "expenses": expense_by_month.get(month, 0.0),
            }
            for month in legacy_months
        ],
        "category_breakdown": [{"category": row.category, "total": _serialize_money(row.total)} for row in category_rows],
        "recent_activity": recent_activity[:12],
        "budget_warnings": budget_warnings,
        "ai_insights": ai_insights,
    }

    monthly_summary_payload = {
        "month": month_start.strftime("%Y-%m"),
        "income": _serialize_money(transaction_income_month),
        "expenses": _serialize_money(transaction_expense_month),
        "savings": _serialize_money(transaction_income_month - transaction_expense_month),
        "savingsRate": round(
            float((transaction_income_month - transaction_expense_month) / transaction_income_month * Decimal("100"))
            if transaction_income_month > 0
            else 0,
            2,
        ),
        "totalBalance": _serialize_money(total_balance),
        "categorySpending": [
            {"category": row.category or "Uncategorized", "total": _serialize_money(row.total)}
            for row in current_month_category_rows
        ],
        "topMerchants": [{"merchant": row.merchant, "total": _serialize_money(row.total)} for row in current_month_merchant_rows],
        "budgetWarnings": budget_warnings,
    }

    return {
        "dashboard": dashboard_payload,
        "monthlySummary": monthly_summary_payload,
        "trends": trends,
        "budgets": budget_payloads,
        "goals": [_serialize_goal(goal) for goal in goals],
        "categories": [{"id": row.id, "name": row.name} for row in categories],
    }


@router.get("/dashboard")
async def get_dashboard_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict:
    cache_key = f"dashboard:{current_user.id}"
    cached = await get_cache(cache_key)
    if cached:
        return cached

    result = _build_dashboard_overview(current_user, db)["dashboard"]
    await set_cache(cache_key, result, ttl=300)
    return result


@router.get("/api/dashboard/overview")
async def get_dashboard_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict:
    cache_key = f"dashboard_overview:{current_user.id}"
    cached = await get_cache(cache_key)
    if cached:
        return cached

    result = _build_dashboard_overview(current_user, db)
    await set_cache(cache_key, result, ttl=300)
    return result
