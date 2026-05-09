"""
Recurring transaction patterns API router.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Category, RecurringPattern, User
from oauth2 import get_current_user
from recurring import scan_recurring_patterns
from schemas import AutoCreateToggle

router = APIRouter(prefix="/recurring", tags=["recurring"])


def _serialize_pattern(p: RecurringPattern) -> dict:
    return {
        "id": p.id,
        "description": p.description,
        "amount": float(p.amount),
        "transaction_type": p.transaction_type,
        "category_id": p.category_id,
        "category_name": p.category.name if p.category else None,
        "frequency": p.frequency,
        "avg_gap_days": p.avg_gap_days,
        "occurrence_count": p.occurrence_count,
        "status": p.status,
        "auto_create": p.auto_create,
        "last_seen_date": p.last_seen_date.isoformat() if p.last_seen_date else None,
        "next_expected_date": p.next_expected_date.isoformat() if p.next_expected_date else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/patterns")
def list_patterns(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all recurring patterns for the current user."""
    patterns = (
        db.query(RecurringPattern)
        .filter(RecurringPattern.user_id == current_user.id)
        .order_by(RecurringPattern.created_at.desc())
        .all()
    )
    return {"patterns": [_serialize_pattern(p) for p in patterns]}


@router.post("/patterns/{pattern_id}/confirm")
def confirm_pattern(
    pattern_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirm a suggested recurring pattern."""
    pattern = (
        db.query(RecurringPattern)
        .filter(
            RecurringPattern.id == pattern_id,
            RecurringPattern.user_id == current_user.id,
        )
        .first()
    )
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    pattern.status = "confirmed"
    db.commit()
    return {"message": "Pattern confirmed", "pattern": _serialize_pattern(pattern)}


@router.post("/patterns/{pattern_id}/dismiss")
def dismiss_pattern(
    pattern_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dismiss a suggested recurring pattern."""
    pattern = (
        db.query(RecurringPattern)
        .filter(
            RecurringPattern.id == pattern_id,
            RecurringPattern.user_id == current_user.id,
        )
        .first()
    )
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    pattern.status = "dismissed"
    db.commit()
    return {"message": "Pattern dismissed"}


@router.put("/patterns/{pattern_id}/auto-create")
def toggle_auto_create(
    pattern_id: int,
    body: AutoCreateToggle,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toggle auto-creation for a confirmed recurring pattern."""
    pattern = (
        db.query(RecurringPattern)
        .filter(
            RecurringPattern.id == pattern_id,
            RecurringPattern.user_id == current_user.id,
        )
        .first()
    )
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    if pattern.status != "confirmed":
        raise HTTPException(
            status_code=400,
            detail="Pattern must be confirmed before enabling auto-create",
        )

    pattern.auto_create = body.enabled
    db.commit()
    return {
        "message": f"Auto-create {'enabled' if body.enabled else 'disabled'}",
        "pattern": _serialize_pattern(pattern),
    }


@router.delete("/patterns/{pattern_id}")
def delete_pattern(
    pattern_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a recurring pattern."""
    pattern = (
        db.query(RecurringPattern)
        .filter(
            RecurringPattern.id == pattern_id,
            RecurringPattern.user_id == current_user.id,
        )
        .first()
    )
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    db.delete(pattern)
    db.commit()
    return {"message": "Pattern deleted"}


@router.post("/scan")
def trigger_scan(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually trigger a recurring pattern scan for the current user."""
    new_patterns = scan_recurring_patterns(db, current_user.id)
    return {
        "message": f"Scan complete. {len(new_patterns)} new pattern(s) found.",
        "new_patterns": new_patterns,
    }
