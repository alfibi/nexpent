from sqlalchemy.orm import Session, joinedload

from models import ExpenseNew, Income


def _serialize_expense(expense: ExpenseNew):
    return {
        "id": expense.id,
        "transaction_type": "expense",
        "date": expense.date.isoformat(),
        "amount": float(expense.amount),
        "primary_label": expense.category.name if expense.category else "Expense",
        "secondary_label": expense.subcategory.name if expense.subcategory else "",
        "description": expense.description or "",
        "payment_method": expense.payment_method.name if expense.payment_method else None,
    }


def _serialize_income(income: Income):
    date_value = income.date.isoformat() if income.date else None
    return {
        "id": income.id,
        "transaction_type": "income",
        "date": date_value,
        "amount": float(income.amount),
        "primary_label": income.type.replace("_", " ").title() if income.type else "Income",
        "secondary_label": income.source,
        "description": income.description or "",
        "payment_method": income.payment_method,
    }


def fetch_latest_activity(db: Session, user, limit: int = 5):
    expenses = (
        db.query(ExpenseNew)
        .options(
            joinedload(ExpenseNew.category),
            joinedload(ExpenseNew.subcategory),
            joinedload(ExpenseNew.payment_method),
        )
        .filter(ExpenseNew.user_id == user.id)
        .order_by(ExpenseNew.date.desc(), ExpenseNew.id.desc())
        .limit(limit)
        .all()
    )
    income = (
        db.query(Income)
        .filter(Income.user_id == user.id)
        .order_by(Income.date.desc(), Income.id.desc())
        .limit(limit)
        .all()
    )

    activity = [_serialize_expense(row) for row in expenses] + [_serialize_income(row) for row in income]
    activity.sort(key=lambda item: (item["date"] or "", item["id"]), reverse=True)
    return activity[:limit]


def fetch_all_transactions(db: Session, user):
    expenses = (
        db.query(ExpenseNew)
        .options(
            joinedload(ExpenseNew.category),
            joinedload(ExpenseNew.subcategory),
            joinedload(ExpenseNew.payment_method),
        )
        .filter(ExpenseNew.user_id == user.id)
        .order_by(ExpenseNew.date.desc(), ExpenseNew.id.desc())
        .all()
    )
    income = (
        db.query(Income)
        .filter(Income.user_id == user.id)
        .order_by(Income.date.desc(), Income.id.desc())
        .all()
    )

    activity = [_serialize_expense(row) for row in expenses] + [_serialize_income(row) for row in income]
    activity.sort(key=lambda item: (item["date"] or "", item["id"]), reverse=True)
    return activity
