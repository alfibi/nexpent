import calendar
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models import BankAccount, Budget, MonthlySummary, Transaction, User
from oauth2 import get_current_user
from services.calculation_service import budgetRemaining, savingsRate, totalExpenses, totalIncome
from utils.financial import parse_date

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _date_range_for_month(month: Optional[str]) -> tuple[date, date, str]:
    if month:
        year, month_num = [int(part) for part in month.split("-", 1)]
    else:
        today = date.today()
        year, month_num = today.year, today.month
    last_day = calendar.monthrange(year, month_num)[1]
    key = f"{year:04d}-{month_num:02d}"
    return date(year, month_num, 1), date(year, month_num, last_day), key


def _serialize_money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _budget_warnings(db: Session, user_id: int, category_spend: dict[str, Decimal]) -> list[dict]:
    budgets = db.query(Budget).filter(Budget.user_id == user_id).all()
    warnings = []
    for budget in budgets:
        category_name = budget.category.name if budget.category else "Uncategorized"
        spent = category_spend.get(category_name, Decimal("0.00"))
        limit_amount = Decimal(str(budget.monthly_limit))
        pct = (spent / limit_amount * Decimal("100")) if limit_amount > 0 else Decimal("0.00")
        if pct >= 80:
            warnings.append(
                {
                    "budgetId": budget.id,
                    "category": category_name,
                    "spent": _serialize_money(spent),
                    "limit": _serialize_money(limit_amount),
                    "remaining": _serialize_money(budgetRemaining(limit_amount, spent)),
                    "status": "exceeded" if pct >= 100 else "warning",
                    "percentage": float(pct.quantize(Decimal("0.01"))),
                }
            )
    return warnings


@router.get("/monthly-summary")
def monthly_summary(
    month: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end, month_key = _date_range_for_month(month)
    rows = (
        db.query(Transaction)
        .filter(Transaction.user_id == current_user.id, Transaction.date >= start, Transaction.date <= end)
        .order_by(Transaction.date.desc())
        .all()
    )
    income = totalIncome(rows)
    expenses = totalExpenses(rows)
    saved = income - expenses
    rate = savingsRate(income, saved)
    category_spend: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    merchant_spend: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for tx in rows:
        if tx.amount < 0:
            category_spend[tx.category or "Uncategorized"] += abs(tx.amount)
            merchant_spend[tx.merchant or "Unknown"] += abs(tx.amount)
    balances = (
        db.query(BankAccount)
        .filter(BankAccount.user_id == current_user.id, BankAccount.status == "active")
        .all()
    )
    total_balance = sum((Decimal(str(account.balance)) for account in balances), Decimal("0.00"))
    payload = {
        "month": month_key,
        "income": _serialize_money(income),
        "expenses": _serialize_money(expenses),
        "savings": _serialize_money(saved),
        "savingsRate": float(rate),
        "totalBalance": _serialize_money(total_balance),
        "categorySpending": [
            {"category": key, "total": _serialize_money(value)}
            for key, value in sorted(category_spend.items(), key=lambda item: item[1], reverse=True)
        ],
        "topMerchants": [
            {"merchant": key, "total": _serialize_money(value)}
            for key, value in sorted(merchant_spend.items(), key=lambda item: item[1], reverse=True)[:5]
        ],
        "budgetWarnings": _budget_warnings(db, current_user.id, category_spend),
    }
    summary = (
        db.query(MonthlySummary)
        .filter(MonthlySummary.user_id == current_user.id, MonthlySummary.month == month_key, MonthlySummary.currency == "USD")
        .first()
    )
    if not summary:
        summary = MonthlySummary(user_id=current_user.id, month=month_key, currency="USD", country="US")
        db.add(summary)
    summary.income = income
    summary.expenses = expenses
    summary.savings = saved
    summary.savings_rate = rate
    summary.payload = json.dumps(payload)
    db.commit()
    return payload


@router.get("/category-spending")
def category_spending(
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Transaction).filter(Transaction.user_id == current_user.id, Transaction.amount < 0)
    if startDate:
        query = query.filter(Transaction.date >= parse_date(startDate))
    if endDate:
        query = query.filter(Transaction.date <= parse_date(endDate))
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for tx in query.all():
        totals[tx.category or "Uncategorized"] += abs(tx.amount)
    return {
        "categories": [
            {"category": key, "total": _serialize_money(value)}
            for key, value in sorted(totals.items(), key=lambda item: item[1], reverse=True)
        ]
    }


@router.get("/trends")
def trends(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Transaction).filter(Transaction.user_id == current_user.id).order_by(Transaction.date.asc()).all()
    monthly: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"income": Decimal("0.00"), "expenses": Decimal("0.00")})
    for tx in rows:
        key = tx.date.strftime("%Y-%m")
        if tx.amount > 0:
            monthly[key]["income"] += tx.amount
        elif tx.amount < 0:
            monthly[key]["expenses"] += abs(tx.amount)
    return {
        "trends": [
            {
                "month": month,
                "income": _serialize_money(values["income"]),
                "expenses": _serialize_money(values["expenses"]),
                "savings": _serialize_money(values["income"] - values["expenses"]),
            }
            for month, values in sorted(monthly.items())
        ]
    }
