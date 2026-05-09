"""
Budget tracking API router.

Provides CRUD for per-category monthly budgets and computes
current-month spending totals using SQL aggregation.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from anyio import from_thread
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from cache import invalidate_cache, user_financial_cache_keys
from database import get_db
from models import Budget, Category, ExpenseNew, Transaction, User
from oauth2 import get_current_user
from schemas import BudgetCreate, BudgetUpdate

router = APIRouter(prefix="/budgets", tags=["budgets"])


def _current_period_range(period: str = "monthly") -> tuple[date, date]:
    """Return an inclusive/exclusive date range for weekly or monthly budgets."""
    today = date.today()
    if period == "weekly":
        first_day = today - timedelta(days=today.weekday())
        return first_day, first_day + timedelta(days=7)

    first_day = today.replace(day=1)
    if today.month == 12:
        last_day = today.replace(year=today.year + 1, month=1, day=1)
    else:
        last_day = today.replace(month=today.month + 1, day=1)
    return first_day, last_day


def _get_category_spending_maps(
    db: Session,
    user_id: int,
    period: str = "monthly",
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

    legacy_map = {row.category_id: Decimal(str(row.total or 0)) for row in legacy_rows}
    transaction_map = {(row.category or "Uncategorized"): Decimal(str(row.total or 0)) for row in transaction_rows}
    return legacy_map, transaction_map


def _status_from_pct(pct: float) -> str:
    if pct >= 100:
        return "exceeded"
    if pct >= 80:
        return "warning"
    return "safe"


def _serialize_budget(budget: Budget, spent: Decimal) -> dict:
    limit_value = Decimal(str(budget.monthly_limit))
    remaining = max(limit_value - spent, Decimal("0.00"))
    pct = round(float((spent / limit_value * Decimal("100")) if limit_value > 0 else 0), 1)

    return {
        "id": budget.id,
        "category_id": budget.category_id,
        "category_name": budget.category.name if budget.category else "Unknown",
        "monthly_limit": float(limit_value),
        "period": budget.period,
        "currency": budget.currency,
        "country": budget.country,
        "spent": round(float(spent), 2),
        "remaining": round(float(remaining), 2),
        "percentage": pct,
        "status": _status_from_pct(pct),
    }


@router.get("")
def list_budgets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all budgets with current month spending data."""
    budgets = (
        db.query(Budget)
        .options(joinedload(Budget.category))
        .filter(Budget.user_id == current_user.id)
        .order_by(Budget.created_at)
        .all()
    )

    spending_by_period: dict[str, tuple[dict[int, Decimal], dict[str, Decimal]]] = {}
    result = []
    for b in budgets:
        if b.period not in spending_by_period:
            spending_by_period[b.period] = _get_category_spending_maps(db, current_user.id, b.period)
        legacy_spending, transaction_spending = spending_by_period[b.period]
        category_name = b.category.name if b.category else "Unknown"
        spent = legacy_spending.get(b.category_id, Decimal("0.00")) + transaction_spending.get(category_name, Decimal("0.00"))
        result.append(_serialize_budget(b, spent))

    return {"budgets": result}


@router.post("")
def create_or_update_budget(
    data: BudgetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create or update a budget for a category (upsert)."""
    # Validate category
    category = db.query(Category).filter(Category.id == data.category_id).first()
    if not category:
        raise HTTPException(status_code=400, detail="Invalid category")

    if data.monthly_limit <= 0:
        raise HTTPException(status_code=400, detail="Budget limit must be positive")
    period = (data.period or "monthly").lower()
    if period not in {"monthly", "weekly"}:
        raise HTTPException(status_code=400, detail="Budget period must be monthly or weekly")

    # Check if budget already exists for this user + category
    existing = (
        db.query(Budget)
        .filter(
            Budget.user_id == current_user.id,
            Budget.category_id == data.category_id,
            Budget.period == period,
        )
        .first()
    )

    if existing:
        existing.monthly_limit = data.monthly_limit
        existing.currency = (data.currency or existing.currency or "USD").upper()
        existing.country = (data.country or existing.country or "US").upper()
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))

        legacy_spending, transaction_spending = _get_category_spending_maps(db, current_user.id, existing.period)
        category_name = existing.category.name if existing.category else "Unknown"
        spent = legacy_spending.get(data.category_id, Decimal("0.00")) + transaction_spending.get(category_name, Decimal("0.00"))
        return {
            "message": "Budget updated",
            "budget": _serialize_budget(existing, spent),
        }

    budget = Budget(
        user_id=current_user.id,
        category_id=data.category_id,
        monthly_limit=data.monthly_limit,
        period=period,
        currency=(data.currency or "USD").upper(),
        country=(data.country or "US").upper(),
    )
    db.add(budget)
    db.commit()
    db.refresh(budget)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))

    legacy_spending, transaction_spending = _get_category_spending_maps(db, current_user.id, budget.period)
    category_name = budget.category.name if budget.category else "Unknown"
    spent = legacy_spending.get(data.category_id, Decimal("0.00")) + transaction_spending.get(category_name, Decimal("0.00"))
    return {
        "message": "Budget created",
        "budget": _serialize_budget(budget, spent),
    }


@router.put("/{budget_id}")
def update_budget(
    budget_id: int,
    data: BudgetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    budget = (
        db.query(Budget)
        .filter(Budget.id == budget_id, Budget.user_id == current_user.id)
        .first()
    )
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    updates = data.dict(exclude_unset=True)
    if "category_id" in updates and updates["category_id"] is not None:
        category = db.query(Category).filter(Category.id == updates["category_id"]).first()
        if not category:
            raise HTTPException(status_code=400, detail="Invalid category")
        budget.category_id = updates["category_id"]
    if "monthly_limit" in updates and updates["monthly_limit"] is not None:
        if updates["monthly_limit"] <= 0:
            raise HTTPException(status_code=400, detail="Budget limit must be positive")
        budget.monthly_limit = updates["monthly_limit"]
    if "period" in updates and updates["period"]:
        period = updates["period"].lower()
        if period not in {"monthly", "weekly"}:
            raise HTTPException(status_code=400, detail="Budget period must be monthly or weekly")
        budget.period = period
    if "currency" in updates and updates["currency"]:
        budget.currency = updates["currency"].upper()
    if "country" in updates and updates["country"]:
        budget.country = updates["country"].upper()

    budget.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(budget)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    legacy_spending, transaction_spending = _get_category_spending_maps(db, current_user.id, budget.period)
    category_name = budget.category.name if budget.category else "Unknown"
    spent = legacy_spending.get(budget.category_id, Decimal("0.00")) + transaction_spending.get(category_name, Decimal("0.00"))
    return {"message": "Budget updated", "budget": _serialize_budget(budget, spent)}


@router.delete("/{budget_id}")
def delete_budget(
    budget_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a budget."""
    budget = (
        db.query(Budget)
        .filter(
            Budget.id == budget_id,
            Budget.user_id == current_user.id,
        )
        .first()
    )
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    db.delete(budget)
    db.commit()
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return {"message": "Budget deleted"}


@router.get("/summary")
def budget_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get aggregate budget summary for current month."""
    budgets = (
        db.query(Budget)
        .options(joinedload(Budget.category))
        .filter(Budget.user_id == current_user.id)
        .all()
    )

    spending_by_period: dict[str, tuple[dict[int, Decimal], dict[str, Decimal]]] = {}
    total_budgeted = sum(float(b.monthly_limit) for b in budgets)
    total_spent = 0.0
    warnings = []
    for b in budgets:
        if b.period not in spending_by_period:
            spending_by_period[b.period] = _get_category_spending_maps(db, current_user.id, b.period)
        legacy_spending, transaction_spending = spending_by_period[b.period]
        category_name = b.category.name if b.category else "Unknown"
        spent = float(
            legacy_spending.get(b.category_id, Decimal("0.00")) + transaction_spending.get(category_name, Decimal("0.00"))
        )
        total_spent += spent
        limit_val = float(b.monthly_limit)
        if limit_val > 0:
            pct = spent / limit_val * 100
            if pct >= 100:
                warnings.append(f"🔴 {category_name}: Budget exceeded ({pct:.0f}%)")
            elif pct >= 80:
                warnings.append(f"🟡 {category_name}: Approaching limit ({pct:.0f}%)")

    total_remaining = max(total_budgeted - total_spent, 0)

    return {
        "total_budgeted": round(total_budgeted, 2),
        "total_spent": round(total_spent, 2),
        "total_remaining": round(total_remaining, 2),
        "overall_percentage": round(
            (total_spent / total_budgeted * 100) if total_budgeted > 0 else 0, 1
        ),
        "warnings": warnings,
        "budget_count": len(budgets),
    }
