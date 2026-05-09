import io
import matplotlib
matplotlib.use("Agg")  # Required for FastAPI servers

import matplotlib.pyplot as plt
import pandas as pd


# ---------------------------------------------------------
# INTERNAL HELPER — consistent PNG export
# ---------------------------------------------------------

def _save_fig_to_buffer(fig):
    """Render a Matplotlib figure to an in-memory PNG buffer."""
    plt.tight_layout()
    fig.subplots_adjust(top=0.95, bottom=0.12)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


# ---------------------------------------------------------
# CATEGORY TOTALS (BAR CHART)
# ---------------------------------------------------------

def plot_category_totals(df):
    totals = df.groupby("category")["amount"].sum().sort_values()

    fig, ax = plt.subplots(figsize=(8, 5))
    totals.plot(kind="barh", color="skyblue", ax=ax)

    ax.set_title("Total Expenses by Category")
    ax.set_xlabel("Amount ($)")

    return _save_fig_to_buffer(fig)


# ---------------------------------------------------------
# SUBCATEGORY BREAKDOWN (BAR CHART)
# ---------------------------------------------------------

def plot_subcategories(df, category):
    sub_df = df[df["category"] == category]
    subs = sub_df.groupby("subcategory")["amount"].sum().sort_values()

    fig, ax = plt.subplots(figsize=(8, 5))
    subs.plot(kind="barh", color="lightgreen", ax=ax)

    ax.set_title(f"{category} Breakdown")
    ax.set_xlabel("Amount ($)")

    return _save_fig_to_buffer(fig)


# ---------------------------------------------------------
# MONTHLY TREND (LINE CHART)
# ---------------------------------------------------------

def plot_monthly_trend(df):
    df = df.dropna(subset=["date"])
    df["year_month"] = df["date"].dt.to_period("M").astype(str)

    monthly_totals = df.groupby("year_month")["amount"].sum()

    fig, ax = plt.subplots(figsize=(10, 5))
    monthly_totals.plot(kind="line", marker="o", color="blue", ax=ax)

    ax.set_title("Monthly Spending Trend")
    ax.set_xlabel("Month")
    ax.set_ylabel("Total Spent ($)")
    ax.grid(True)

    return _save_fig_to_buffer(fig)


# ---------------------------------------------------------
# CATEGORY PIE CHART
# ---------------------------------------------------------

def plot_category_pie(df):
    totals = df.groupby("category")["amount"].sum()

    fig, ax = plt.subplots(figsize=(8, 8))  # large square canvas

    wedges, texts, autotexts = ax.pie(
        totals,
        labels=totals.index,
        autopct="%1.1f%%",
        startangle=90,
        pctdistance=0.7,
        labeldistance=1.1
    )

    # Force perfect circle
    ax.set_aspect("equal")

    # Improve label readability
    for t in texts:
        t.set_fontsize(12)
        t.set_horizontalalignment("center")

    for a in autotexts:
        a.set_fontsize(11)
        a.set_color("white")
        a.set_weight("bold")

    ax.set_title("Spending by Category", fontsize=16, pad=20)

    # DO NOT use tight_layout() for pie charts — it causes distortion
    fig.subplots_adjust(left=0.05, right=0.95, top=0.92, bottom=0.08)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
