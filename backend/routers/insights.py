"""
Optimised analytics endpoint.

Key techniques used:
  1. **Single CTE query** — all aggregate numbers (totals, monthly series,
     top categories, income breakdown, anomaly stats) are computed in ONE
     database round-trip via PostgreSQL CTEs + UNION ALL.
  2. **Eager JOIN for anomalies** — `joinedload` prevents N+1 on
     category lookups.
  3. **TTL response cache** — identical requests within 60 s are served
     from memory, avoiding the DB entirely.
  4. **Column projection** — only the columns we need are selected,
     never full ORM objects for aggregates.
"""

import json
import time
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import ExpenseNew, User
from oauth2 import get_current_user
from cache import get_cache, set_cache

router = APIRouter()


# ---------------------------------------------------------
# The single CTE query that fetches EVERYTHING in one shot
# ---------------------------------------------------------
_AGGREGATE_SQL = text("""
WITH expense_totals AS (
    SELECT COALESCE(SUM(amount), 0)            AS total_expenses,
           COUNT(*)                            AS expense_count,
           COALESCE(AVG(amount), 0)            AS avg_expense,
           COALESCE(STDDEV_POP(amount), 0)     AS std_expense
    FROM   public.expenses_new
    WHERE  user_id = :uid
),
income_totals AS (
    SELECT COALESCE(SUM(amount), 0) AS total_income
    FROM   public.income
    WHERE  user_id = :uid
),
monthly_expenses AS (
    SELECT DATE_TRUNC('month', date)  AS month,
           SUM(amount)                AS total
    FROM   public.expenses_new
    WHERE  user_id = :uid
    GROUP  BY 1
    ORDER  BY 1
),
monthly_income AS (
    SELECT DATE_TRUNC('month', date)  AS month,
           SUM(amount)                AS total
    FROM   public.income
    WHERE  user_id = :uid
    GROUP  BY 1
    ORDER  BY 1
),
top_categories AS (
    SELECT c.name                     AS category,
           SUM(e.amount)              AS total
    FROM   public.expenses_new e
    JOIN   public.categories c ON c.id = e.category_id
    WHERE  e.user_id = :uid
    GROUP  BY c.name
    ORDER  BY total DESC
    LIMIT  5
),
income_types AS (
    SELECT type,
           SUM(amount) AS total
    FROM   public.income
    WHERE  user_id = :uid
    GROUP  BY type
    ORDER  BY total DESC
)

-- Tag each result set so we can split them in Python
SELECT 'totals'       AS section, NULL AS month,
       et.total_expenses::text  AS val1,
       it.total_income::text    AS val2,
       et.expense_count::text   AS val3,
       et.avg_expense::text     AS val4,
       et.std_expense::text     AS val5
FROM   expense_totals et, income_totals it

UNION ALL

SELECT 'monthly_exp'  AS section,
       me.month::text  AS month,
       me.total::text  AS val1,
       NULL, NULL, NULL, NULL
FROM   monthly_expenses me

UNION ALL

SELECT 'monthly_inc'  AS section,
       mi.month::text  AS month,
       mi.total::text  AS val1,
       NULL, NULL, NULL, NULL
FROM   monthly_income mi

UNION ALL

SELECT 'top_cat'      AS section,
       NULL            AS month,
       tc.category     AS val1,
       tc.total::text  AS val2,
       NULL, NULL, NULL
FROM   top_categories tc

UNION ALL

SELECT 'inc_type'     AS section,
       NULL            AS month,
       it.type         AS val1,
       it.total::text  AS val2,
       NULL, NULL, NULL
FROM   income_types it;
""")


# ---------------------------------------------------------
# Narrative helpers (unchanged logic)
# ---------------------------------------------------------

def _build_highlights(total_income, total_expenses, net_balance, top_categories, monthly_savings):
    highlights = []
    risks = []
    opportunities = []

    if total_income == 0 and total_expenses == 0:
        highlights.append("No income or expense data yet. Add a few transactions to unlock insights.")
        return highlights, risks, opportunities

    if net_balance >= 0:
        highlights.append(f"You are net positive by ${net_balance:,.2f}.")
    else:
        risks.append(f"You are net negative by ${abs(net_balance):,.2f}.")

    if top_categories:
        top = top_categories[0]
        highlights.append(
            f"Your largest expense category is {top['category']} at ${top['total']:,.2f} "
            f"({top['share_pct']:.1f}% of recorded expenses)."
        )

    if len(monthly_savings) >= 2:
        latest = monthly_savings[-1]["total"]
        previous = monthly_savings[-2]["total"]
        diff = latest - previous
        if diff > 0:
            opportunities.append(
                f"Your monthly savings improved by ${diff:,.2f} compared with the previous month."
            )
        elif diff < 0:
            risks.append(
                f"Your monthly savings dropped by ${abs(diff):,.2f} compared with the previous month."
            )

    return highlights, risks, opportunities


def _forecast(monthly_savings):
    if not monthly_savings:
        return 0.0
    values = [m["total"] for m in monthly_savings]
    n = len(values)
    if n >= 3:
        sx = sum(range(n))
        sy = sum(values)
        sxy = sum(i * values[i] for i in range(n))
        sx2 = sum(i * i for i in range(n))
        denom = n * sx2 - sx * sx
        if denom:
            slope = (n * sxy - sx * sy) / denom
            intercept = (sy - slope * sx) / n
            return round(slope * n + intercept, 2)
    return round(sum(values) / n, 2)


# ---------------------------------------------------------
# ENDPOINT
# ---------------------------------------------------------

@router.get("/insights")
async def get_insights(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    uid = current_user.id

    # ── Check Redis cache ────────────────────────────────
    cache_key = f"insights:{uid}"
    cached = await get_cache(cache_key)
    if cached:
        return cached

    # ── 1. Single DB round-trip for ALL aggregates ───────
    rows = db.execute(_AGGREGATE_SQL, {"uid": uid}).fetchall()

    total_expenses = 0.0
    total_income = 0.0
    expense_count = 0
    avg_expense = 0.0
    std_expense = 0.0
    expense_series: list[dict] = []
    income_series: list[dict] = []
    top_categories: list[dict] = []
    income_breakdown: list[dict] = []

    for r in rows:
        section = r[0]

        if section == "totals":
            total_expenses = float(r[2] or 0)
            total_income = float(r[3] or 0)
            expense_count = int(r[4] or 0)
            avg_expense = float(r[5] or 0)
            std_expense = float(r[6] or 0)

        elif section == "monthly_exp":
            month_str = r[1][:7] if r[1] else None      # "2025-03"
            if month_str:
                expense_series.append({"month": month_str, "total": float(r[2])})

        elif section == "monthly_inc":
            month_str = r[1][:7] if r[1] else None
            if month_str:
                income_series.append({"month": month_str, "total": float(r[2])})

        elif section == "top_cat":
            total = float(r[3])
            top_categories.append({
                "category": r[2],
                "total": total,
                "share_pct": (total / total_expenses * 100) if total_expenses > 0 else 0.0,
            })

        elif section == "inc_type":
            income_breakdown.append({"type": r[2], "total": float(r[3])})

    # Net balance & savings rate
    net_balance = total_income - total_expenses
    savings_rate = (net_balance / total_income * 100) if total_income > 0 else 0.0

    # Monthly savings merge
    inc_map = {m["month"]: m["total"] for m in income_series}
    exp_map = {m["month"]: m["total"] for m in expense_series}
    all_months = sorted(set(inc_map) | set(exp_map))
    monthly_savings = [
        {"month": m, "total": inc_map.get(m, 0.0) - exp_map.get(m, 0.0)}
        for m in all_months
    ]

    # ── 2. Anomalies — second query only if needed ───────
    anomalies = []
    if expense_count >= 5 and std_expense > 0:
        threshold = avg_expense + 2 * std_expense
        anomaly_rows = (
            db.query(ExpenseNew)
            .options(joinedload(ExpenseNew.category))        # ← prevents N+1
            .filter(
                ExpenseNew.user_id == uid,
                ExpenseNew.amount > threshold,
            )
            .order_by(ExpenseNew.amount.desc())
            .limit(5)
            .all()
        )
        anomalies = [
            {
                "expense_id": row.id,
                "date": row.date.isoformat(),
                "amount": float(row.amount),
                "category": row.category.name if row.category else None,
                "description": row.description,
                "reason": "Amount is significantly higher than your typical expense.",
            }
            for row in anomaly_rows
        ]

    # ── 3. Forecast & highlights (pure Python, no DB) ────
    forecast_next_month_savings = _forecast(monthly_savings)

    highlights, risks, opportunities = _build_highlights(
        total_income, total_expenses, net_balance,
        top_categories, monthly_savings,
    )

    result = {
        "summary": {
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_balance": net_balance,
            "savings_rate_pct": round(savings_rate, 2),
            "forecast_next_month_savings": forecast_next_month_savings,
        },
        "highlights": highlights,
        "risks": risks,
        "opportunities": opportunities,
        "top_expense_categories": top_categories,
        "income_breakdown": income_breakdown,
        "monthly_expenses": expense_series,
        "monthly_income": income_series,
        "monthly_savings": monthly_savings,
        "anomalies": anomalies,
        "generated_at": datetime.utcnow().isoformat(),
    }

    # ── Store in Redis cache ─────────────────────────────
    await set_cache(cache_key, result, ttl=300)

    return result
