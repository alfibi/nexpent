function money(value) {
  return Number(value || 0);
}

function notificationId(parts) {
  return parts.filter(Boolean).join(":").toLowerCase().replace(/\s+/g, "-");
}

function severityRank(severity) {
  return { critical: 0, high: 1, medium: 2, low: 3 }[severity] ?? 4;
}

function transactionLabel(transaction) {
  return transaction.merchant || transaction.primary_label || transaction.description || transaction.category || "Transaction";
}

export function buildMoneyHubNotifications({ overview, transactions = [], aiInsights = [], financialTools }) {
  const dashboard = overview?.dashboard || {};
  const summary = dashboard.summary || {};
  const monthlySummary = overview?.monthlySummary || {};
  const notifications = [];

  for (const warning of dashboard.budget_warnings || monthlySummary.budgetWarnings || []) {
    const isExceeded = warning.status === "exceeded" || money(warning.percentage) >= 100;
    notifications.push({
      id: notificationId(["budget", warning.budgetId, warning.category, warning.status]),
      severity: isExceeded ? "critical" : "high",
      source: "AI Guard",
      title: isExceeded ? "Budget exceeded" : "Budget almost used",
      message: `${warning.category} is at ${Math.round(money(warning.percentage))}% of budget.`,
      actionPath: "/planner",
      createdAt: new Date().toISOString()
    });
  }

  if (money(summary.monthly_income) > 0 && money(summary.monthly_expenses) > money(summary.monthly_income)) {
    notifications.push({
      id: notificationId(["cashflow", "expenses-over-income", summary.monthly_income, summary.monthly_expenses]),
      severity: "critical",
      source: "AI Guard",
      title: "Expenses passed income",
      message: "This month’s spending is higher than your income.",
      actionPath: "/ledger",
      createdAt: new Date().toISOString()
    });
  }

  if (money(summary.savings_rate) < 0) {
    notifications.push({
      id: notificationId(["cashflow", "negative-savings-rate", summary.savings_rate]),
      severity: "critical",
      source: "AI Guard",
      title: "Negative savings rate",
      message: "You are spending more than you are saving this month.",
      actionPath: "/planner",
      createdAt: new Date().toISOString()
    });
  } else if (money(summary.monthly_income) > 0 && money(summary.savings_rate) < 10) {
    notifications.push({
      id: notificationId(["cashflow", "low-savings-rate", Math.round(money(summary.savings_rate))]),
      severity: "high",
      source: "AI Guard",
      title: "Savings rate is low",
      message: `Your current savings rate is ${money(summary.savings_rate).toFixed(1)}%.`,
      actionPath: "/planner",
      createdAt: new Date().toISOString()
    });
  }

  if (money(summary.forecast_next_month) < 0) {
    notifications.push({
      id: notificationId(["forecast", "negative", summary.forecast_next_month]),
      severity: "high",
      source: "AI Forecast",
      title: "Next month may go negative",
      message: "Your forecast points to negative savings next month.",
      actionPath: "/planner",
      createdAt: new Date().toISOString()
    });
  }

  const expenses = transactions.filter((tx) => money(tx.amount) < 0);
  const averageExpense = expenses.length
    ? expenses.reduce((sum, tx) => sum + Math.abs(money(tx.amount)), 0) / expenses.length
    : 0;
  const largeExpenseThreshold = Math.max(500, averageExpense * 3);
  const largeExpenses = expenses
    .filter((tx) => Math.abs(money(tx.amount)) >= largeExpenseThreshold)
    .slice(0, 3);

  for (const tx of largeExpenses) {
    notifications.push({
      id: notificationId(["large-transaction", tx.id]),
      severity: "high",
      source: "AI Guard",
      title: "Unusually large expense",
      message: `${transactionLabel(tx)} is much higher than your usual expense size.`,
      actionPath: "/ledger",
      createdAt: tx.date || new Date().toISOString()
    });
  }

  const duplicateGroups = new Map();
  for (const tx of transactions) {
    const key = notificationId(["duplicate", tx.date?.substring(0, 10), tx.amount, tx.merchant || tx.description]);
    duplicateGroups.set(key, [...(duplicateGroups.get(key) || []), tx]);
  }
  for (const [key, group] of duplicateGroups) {
    if (group.length < 2) {
      continue;
    }
    notifications.push({
      id: key,
      severity: "medium",
      source: "AI Guard",
      title: "Possible duplicate transaction",
      message: `${transactionLabel(group[0])} appears ${group.length} times with the same amount and date.`,
      actionPath: "/ledger",
      createdAt: group[0].date || new Date().toISOString()
    });
  }

  for (const tx of expenses.filter((item) => (item.category || "").toLowerCase() === "uncategorized" && Math.abs(money(item.amount)) >= 100).slice(0, 3)) {
    notifications.push({
      id: notificationId(["uncategorized", tx.id]),
      severity: "medium",
      source: "AI Guard",
      title: "Large uncategorized spend",
      message: `${transactionLabel(tx)} needs a category for better planning.`,
      actionPath: "/ledger",
      createdAt: tx.date || new Date().toISOString()
    });
  }

  const subscriptionSummary = financialTools?.subscriptionSummary;
  if (subscriptionSummary && money(summary.monthly_income) > 0 && money(subscriptionSummary.monthlyCost) > money(summary.monthly_income) * 0.15) {
    notifications.push({
      id: notificationId(["subscriptions", "high-cost", Math.round(money(subscriptionSummary.monthlyCost))]),
      severity: "medium",
      source: "AI Guard",
      title: "Recurring costs are high",
      message: "Your active recurring charges are taking a large share of monthly income.",
      actionPath: "/planner",
      createdAt: new Date().toISOString()
    });
  }

  for (const insight of aiInsights.slice(0, 3)) {
    const risks = Array.isArray(insight.payload?.risks) ? insight.payload.risks : [];
    for (const risk of risks.slice(0, 2)) {
      notifications.push({
        id: notificationId(["ai-risk", insight.id, risk]),
        severity: "medium",
        source: "AI Advisor",
        title: insight.title || "AI risk detected",
        message: String(risk),
        actionPath: "/advisor",
        createdAt: insight.createdAt || new Date().toISOString()
      });
    }
  }

  const byId = new Map();
  for (const item of notifications) {
    byId.set(item.id, item);
  }
  return [...byId.values()].sort((a, b) => severityRank(a.severity) - severityRank(b.severity));
}
