from datetime import date
from decimal import Decimal
from typing import Optional

from anyio import from_thread
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cache import invalidate_cache, user_financial_cache_keys
from database import get_db
from models import SavingsGoal, User
from oauth2 import get_current_user
from services.audit_service import write_audit_log
from services.calculation_service import goalProgress, requiredMonthlySavings
from utils.financial import money, normalize_country, normalize_currency, parse_date

router = APIRouter(prefix="/api/goals", tags=["savings-goals"])


class GoalCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    targetAmount: Decimal = Field(..., gt=0)
    currentAmount: Optional[Decimal] = 0
    currency: Optional[str] = "USD"
    country: Optional[str] = "US"
    targetDate: Optional[str] = None


class GoalUpdate(BaseModel):
    name: Optional[str] = None
    targetAmount: Optional[Decimal] = None
    currentAmount: Optional[Decimal] = None
    currency: Optional[str] = None
    country: Optional[str] = None
    targetDate: Optional[str] = None


def _months_remaining(target_date: Optional[date]) -> int:
    if not target_date:
        return 0
    today = date.today()
    return max((target_date.year - today.year) * 12 + (target_date.month - today.month), 1)


def _serialize_goal(goal: SavingsGoal) -> dict:
    months = _months_remaining(goal.target_date)
    return {
        "id": goal.id,
        "name": goal.name,
        "targetAmount": float(goal.target_amount),
        "currentAmount": float(goal.current_amount),
        "currency": goal.currency,
        "country": goal.country,
        "targetDate": goal.target_date.isoformat() if goal.target_date else None,
        "progressPercentage": float(goalProgress(goal.current_amount, goal.target_amount)),
        "requiredMonthlySavings": float(requiredMonthlySavings(goal.target_amount, goal.current_amount, months)) if months else 0,
        "createdAt": goal.created_at.isoformat() if goal.created_at else None,
    }


@router.post("")
def create_goal(
    data: GoalCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_amount = money(data.currentAmount or 0)
    target_amount = money(data.targetAmount)
    if current_amount < 0:
        raise HTTPException(status_code=400, detail="Current amount cannot be negative")
    goal = SavingsGoal(
        user_id=current_user.id,
        name=data.name.strip(),
        target_amount=target_amount,
        current_amount=current_amount,
        currency=normalize_currency(data.currency or "USD"),
        country=normalize_country(data.country or "US"),
        target_date=parse_date(data.targetDate) if data.targetDate else None,
    )
    db.add(goal)
    db.flush()
    write_audit_log(db, user_id=current_user.id, action="create_goal", entity_type="savings_goal", entity_id=str(goal.id), request=request)
    db.commit()
    db.refresh(goal)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return _serialize_goal(goal)


@router.get("")
def list_goals(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    goals = db.query(SavingsGoal).filter(SavingsGoal.user_id == current_user.id).order_by(SavingsGoal.created_at.desc()).all()
    return {"goals": [_serialize_goal(goal) for goal in goals]}


@router.put("/{goal_id}")
def update_goal(
    goal_id: int,
    data: GoalUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal = db.query(SavingsGoal).filter(SavingsGoal.id == goal_id, SavingsGoal.user_id == current_user.id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Savings goal not found")
    updates = data.dict(exclude_unset=True)
    if "name" in updates and updates["name"]:
        goal.name = updates["name"].strip()
    if "targetAmount" in updates and updates["targetAmount"] is not None:
        target = money(updates["targetAmount"])
        if target <= 0:
            raise HTTPException(status_code=400, detail="Target amount must be positive")
        goal.target_amount = target
    if "currentAmount" in updates and updates["currentAmount"] is not None:
        current = money(updates["currentAmount"])
        if current < 0:
            raise HTTPException(status_code=400, detail="Current amount cannot be negative")
        goal.current_amount = current
    if "currency" in updates and updates["currency"]:
        goal.currency = normalize_currency(updates["currency"])
    if "country" in updates and updates["country"]:
        goal.country = normalize_country(updates["country"])
    if "targetDate" in updates:
        goal.target_date = parse_date(updates["targetDate"]) if updates["targetDate"] else None
    write_audit_log(db, user_id=current_user.id, action="update_goal", entity_type="savings_goal", entity_id=str(goal.id), request=request)
    db.commit()
    db.refresh(goal)
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return _serialize_goal(goal)


@router.delete("/{goal_id}")
def delete_goal(
    goal_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal = db.query(SavingsGoal).filter(SavingsGoal.id == goal_id, SavingsGoal.user_id == current_user.id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Savings goal not found")
    db.delete(goal)
    write_audit_log(db, user_id=current_user.id, action="delete_goal", entity_type="savings_goal", entity_id=str(goal_id), request=request)
    db.commit()
    from_thread.run(invalidate_cache, *user_financial_cache_keys(current_user.id))
    return {"message": "Savings goal deleted"}
