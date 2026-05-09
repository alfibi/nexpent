from decimal import Decimal

from services.calculation_service import (
    budgetRemaining,
    categorySpend,
    goalProgress,
    monthlySpend,
    requiredMonthlySavings,
    savings,
    savingsRate,
    totalExpenses,
    totalIncome,
)


def test_core_financial_calculations_use_signed_amounts():
    rows = [
        {"amount": "5000.00", "date": "2026-04-01", "category": "Income"},
        {"amount": "-125.25", "date": "2026-04-02", "category": "Groceries"},
        {"amount": "-74.75", "date": "2026-04-04", "category": "Food & Drinks"},
    ]

    assert totalIncome(rows) == Decimal("5000.00")
    assert totalExpenses(rows) == Decimal("200.00")
    assert savings(rows) == Decimal("4800.00")
    assert savingsRate(Decimal("5000.00"), Decimal("4800.00")) == Decimal("96.00")
    assert categorySpend(rows)["Groceries"] == Decimal("125.25")
    assert monthlySpend(rows)["2026-04"] == Decimal("200.00")


def test_budget_and_goal_calculations_are_exact():
    assert budgetRemaining("1000", "750.55") == Decimal("249.45")
    assert budgetRemaining("1000", "1200") == Decimal("0.00")
    assert goalProgress("250", "1000") == Decimal("25.00")
    assert requiredMonthlySavings("1000", "250", 5) == Decimal("150.00")

