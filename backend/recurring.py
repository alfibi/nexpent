"""
Recurring transaction detection engine.

Uses rapidfuzz for fuzzy merchant/description matching and simple time-gap
analysis to detect patterns. No ML — pure rule-based logic.

Rules:
  - Descriptions that match with ≥85% token_sort_ratio are grouped together.
  - Within a group, amounts must be within ±5% tolerance.
  - Time gaps between occurrences must be consistent (±3 days).
  - 3+ consistent occurrences → suggest as recurring.
"""

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, stdev

from rapidfuzz import fuzz
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Budget, Category, ExpenseNew, Income, RecurringPattern

# ── Configuration ────────────────────────────────────────
DESCRIPTION_MATCH_THRESHOLD = 85   # rapidfuzz score 0-100
AMOUNT_TOLERANCE_PCT = 0.05        # ±5%
GAP_TOLERANCE_DAYS = 3             # ±3 days from avg gap
MIN_OCCURRENCES = 3                # need at least 3 to flag

FREQUENCY_MAP = [
    (7, "weekly"),
    (14, "biweekly"),
    (30, "monthly"),
    (90, "quarterly"),
    (365, "yearly"),
]


def _classify_frequency(avg_gap_days: float) -> str:
    """Map average gap in days to a human-readable frequency label."""
    best_label = "monthly"
    best_dist = float("inf")
    for ref_days, label in FREQUENCY_MAP:
        dist = abs(avg_gap_days - ref_days)
        if dist < best_dist:
            best_dist = dist
            best_label = label
    return best_label


def _amounts_match(amounts: list[float]) -> bool:
    """Check if all amounts are within ±5% of each other."""
    if len(amounts) < 2:
        return True
    avg = mean(amounts)
    if avg == 0:
        return all(a == 0 for a in amounts)
    return all(abs(a - avg) / avg <= AMOUNT_TOLERANCE_PCT for a in amounts)


def _gaps_consistent(dates: list[date]) -> tuple[bool, float]:
    """
    Check if date gaps are consistent (±GAP_TOLERANCE_DAYS from average).
    Returns (is_consistent, average_gap_days).
    """
    if len(dates) < 2:
        return False, 0.0

    sorted_dates = sorted(dates)
    gaps = [(sorted_dates[i + 1] - sorted_dates[i]).days for i in range(len(sorted_dates) - 1)]

    if not gaps:
        return False, 0.0

    avg_gap = mean(gaps)
    if avg_gap < 5:
        return False, avg_gap

    if len(gaps) == 1:
        return True, avg_gap

    return all(abs(g - avg_gap) <= GAP_TOLERANCE_DAYS for g in gaps), avg_gap


def _group_by_description(transactions: list[dict]) -> list[list[dict]]:
    """
    Group transactions by fuzzy-matching descriptions.
    Uses rapidfuzz token_sort_ratio for comparison.
    """
    groups: list[list[dict]] = []

    for txn in transactions:
        desc = txn["description"] or ""
        if not desc.strip():
            continue

        placed = False
        for group in groups:
            representative = group[0]["description"] or ""
            score = fuzz.token_sort_ratio(desc.lower(), representative.lower())
            if score >= DESCRIPTION_MATCH_THRESHOLD:
                group.append(txn)
                placed = True
                break

        if not placed:
            groups.append([txn])

    return groups


def _get_existing_patterns(db: Session, user_id: int) -> set[str]:
    """Get a set of description keys for patterns that already exist."""
    patterns = (
        db.query(RecurringPattern.description)
        .filter(RecurringPattern.user_id == user_id)
        .all()
    )
    return {p.description.lower().strip() for p in patterns}


def scan_recurring_patterns(db: Session, user_id: int) -> list[dict]:
    """
    Scan a user's transactions for recurring patterns.
    Returns a list of newly-created pattern dicts.
    """
    existing_keys = _get_existing_patterns(db, user_id)

    # ── Fetch expenses ───────────────────────────────────
    expenses = (
        db.query(ExpenseNew)
        .filter(ExpenseNew.user_id == user_id)
        .order_by(ExpenseNew.date)
        .all()
    )
    expense_txns = [
        {
            "id": e.id,
            "description": e.description or "",
            "amount": float(e.amount),
            "date": e.date,
            "category_id": e.category_id,
            "subcategory_id": e.subcategory_id,
            "payment_method_id": e.payment_method_id,
            "type": "expense",
        }
        for e in expenses
    ]

    # ── Fetch income ─────────────────────────────────────
    incomes = (
        db.query(Income)
        .filter(Income.user_id == user_id)
        .order_by(Income.date)
        .all()
    )
    income_txns = [
        {
            "id": i.id,
            "description": i.source or i.description or "",
            "amount": float(i.amount),
            "date": i.date.date() if hasattr(i.date, "date") else i.date,
            "category_id": None,
            "subcategory_id": None,
            "payment_method_id": None,
            "type": "income",
        }
        for i in incomes
    ]

    all_txns = expense_txns + income_txns
    if len(all_txns) < MIN_OCCURRENCES:
        return []

    # ── Group by description similarity ──────────────────
    groups = _group_by_description(all_txns)
    new_patterns = []

    for group in groups:
        if len(group) < MIN_OCCURRENCES:
            continue

        # Check if amounts are similar
        amounts = [t["amount"] for t in group]
        if not _amounts_match(amounts):
            continue

        # Check if gaps are consistent
        dates = [t["date"] for t in group]
        consistent, avg_gap = _gaps_consistent(dates)
        if not consistent:
            continue

        # Pick representative values
        representative = group[0]
        desc_key = representative["description"].lower().strip()

        # Skip if we already have this pattern
        if desc_key in existing_keys:
            continue

        frequency = _classify_frequency(avg_gap)
        avg_amount = round(mean(amounts), 2)
        sorted_dates = sorted(dates)
        last_seen = sorted_dates[-1]
        next_expected = last_seen + timedelta(days=int(round(avg_gap)))

        pattern = RecurringPattern(
            user_id=user_id,
            description=representative["description"],
            amount=avg_amount,
            transaction_type=representative["type"],
            category_id=representative.get("category_id"),
            subcategory_id=representative.get("subcategory_id"),
            payment_method_id=representative.get("payment_method_id"),
            frequency=frequency,
            avg_gap_days=int(round(avg_gap)),
            occurrence_count=len(group),
            status="suggested",
            auto_create=False,
            last_seen_date=last_seen,
            next_expected_date=next_expected,
        )
        db.add(pattern)
        new_patterns.append({
            "description": representative["description"],
            "amount": avg_amount,
            "frequency": frequency,
            "occurrences": len(group),
        })
        existing_keys.add(desc_key)

    if new_patterns:
        db.commit()

    return new_patterns


def auto_create_recurring_transactions(db: Session) -> int:
    """
    Check all confirmed patterns with auto_create=True.
    If next_expected_date <= today, create the transaction and update the pattern.
    Returns count of transactions created.
    """
    today = date.today()
    patterns = (
        db.query(RecurringPattern)
        .filter(
            RecurringPattern.status == "confirmed",
            RecurringPattern.auto_create.is_(True),
            RecurringPattern.next_expected_date <= today,
        )
        .all()
    )

    created_count = 0

    for pattern in patterns:
        try:
            if pattern.transaction_type == "expense":
                if not pattern.category_id or not pattern.subcategory_id or not pattern.payment_method_id:
                    continue

                exp = ExpenseNew(
                    user_id=pattern.user_id,
                    amount=pattern.amount,
                    category_id=pattern.category_id,
                    subcategory_id=pattern.subcategory_id,
                    payment_method_id=pattern.payment_method_id,
                    description=f"[Auto] {pattern.description}",
                    date=today,
                )
                db.add(exp)
            else:
                inc = Income(
                    user_id=pattern.user_id,
                    amount=pattern.amount,
                    type="earned",
                    source=pattern.description,
                    description=f"[Auto] {pattern.description}",
                    date=today,
                )
                db.add(inc)

            # Update pattern dates
            pattern.last_seen_date = today
            pattern.next_expected_date = today + timedelta(days=pattern.avg_gap_days)
            pattern.occurrence_count += 1
            created_count += 1
        except Exception as exc:
            print(f"⚠️  Failed to auto-create for pattern {pattern.id}: {exc}")
            continue

    if created_count:
        db.commit()

    return created_count
