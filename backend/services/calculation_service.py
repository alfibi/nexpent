from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Mapping, Optional, Union


MoneyLike = Union[Decimal, int, float, str]


def to_money(value: MoneyLike) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _amount(row) -> Decimal:
    if isinstance(row, Mapping):
        return to_money(row.get("amount", 0))
    return to_money(getattr(row, "amount", 0))


def _date(row) -> Optional[date]:
    value = row.get("date") if isinstance(row, Mapping) else getattr(row, "date", None)
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value[:10])
    return None


def _category(row) -> str:
    value = row.get("category") if isinstance(row, Mapping) else getattr(row, "category", None)
    return str(value or "Uncategorized")


def totalIncome(transactions: Iterable) -> Decimal:
    return sum((_amount(row) for row in transactions if _amount(row) > 0), Decimal("0.00"))


def totalExpenses(transactions: Iterable) -> Decimal:
    return abs(sum((_amount(row) for row in transactions if _amount(row) < 0), Decimal("0.00")))


def savings(transactions: Iterable) -> Decimal:
    rows = list(transactions)
    return totalIncome(rows) - totalExpenses(rows)


def savingsRate(income: MoneyLike, saved: MoneyLike) -> Decimal:
    income_value = to_money(income)
    if income_value <= 0:
        return Decimal("0.00")
    return (to_money(saved) / income_value * Decimal("100")).quantize(Decimal("0.01"))


def categorySpend(transactions: Iterable) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in transactions:
        amount = _amount(row)
        if amount < 0:
            totals[_category(row)] += abs(amount)
    return dict(totals)


def monthlySpend(transactions: Iterable) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in transactions:
        amount = _amount(row)
        row_date = _date(row)
        if amount < 0 and row_date:
            totals[row_date.strftime("%Y-%m")] += abs(amount)
    return dict(totals)


def budgetRemaining(limit: MoneyLike, spent: MoneyLike) -> Decimal:
    remaining = to_money(limit) - to_money(spent)
    return max(remaining, Decimal("0.00"))


def goalProgress(current_amount: MoneyLike, target_amount: MoneyLike) -> Decimal:
    target = to_money(target_amount)
    if target <= 0:
        return Decimal("0.00")
    progress = to_money(current_amount) / target * Decimal("100")
    return min(progress, Decimal("100.00")).quantize(Decimal("0.01"))


def requiredMonthlySavings(
    target_amount: MoneyLike,
    current_amount: MoneyLike,
    months_remaining: int,
) -> Decimal:
    if months_remaining <= 0:
        return Decimal("0.00")
    remaining = max(to_money(target_amount) - to_money(current_amount), Decimal("0.00"))
    return (remaining / Decimal(months_remaining)).quantize(Decimal("0.01"))

