import { useState, useEffect } from "react";
import { ShoppingCart, Gamepad2, Film, Pizza, Home, Car, DollarSign, Pencil, Trash2, Plus, RefreshCw, CalendarClock, TrendingUp, CheckCircle2, XCircle } from 'lucide-react';
import { apiRequest, deleteRequest } from "../lib/api";
import { formatCurrency } from "../lib/format";
import Modal from "../components/Modal";
import { invalidateFinancialResources, loadCachedResource, readCachedResource } from "../lib/resourceCache";

export default function Planner() {
  const cachedDashboard = readCachedResource("dashboardOverview");
  const cachedFinancialTools = readCachedResource("financialToolsOverview");
  const cachedConfig = readCachedResource("config");
  const [activePlannerTab, setActivePlannerTab] = useState("budgets");
  const [overview, setOverview] = useState(() => cachedDashboard || null);
  const [budgets, setBudgets] = useState(() => cachedDashboard?.budgets || []);
  const [subscriptions, setSubscriptions] = useState(() => cachedFinancialTools?.subscriptions || []);
  const [subscriptionSummary, setSubscriptionSummary] = useState(() => cachedFinancialTools?.subscriptionSummary || null);
  const [categories, setCategories] = useState(() => cachedConfig?.categories || []);
  const [loading, setLoading] = useState(() => !(cachedDashboard && cachedFinancialTools && cachedConfig));
  const [scanningRecurring, setScanningRecurring] = useState(false);
  const [scanMessage, setScanMessage] = useState("");

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [formData, setFormData] = useState({
    category_id: '',
    monthly_limit: '',
    period: 'monthly'
  });

  async function loadData(options = {}) {
    try {
      const [dashRes, finRes, configRes] = await Promise.all([
        loadCachedResource("dashboardOverview", options),
        loadCachedResource("financialToolsOverview", options),
        loadCachedResource("config")
      ]);
      setOverview(dashRes);
      setBudgets(dashRes.budgets || []);
      setSubscriptions(finRes.subscriptions || []);
      setSubscriptionSummary(finRes.subscriptionSummary || null);
      setCategories(configRes.categories || []);
      
      if (!formData.category_id && configRes.categories?.length > 0) {
        setFormData(prev => ({...prev, category_id: configRes.categories[0].id.toString()}));
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  function handleAdd() {
    setEditingId(null);
    setFormData({
      category_id: categories.length > 0 ? categories[0].id.toString() : '',
      monthly_limit: '',
      period: 'monthly'
    });
    setIsModalOpen(true);
  }

  function handleEdit(b) {
    setEditingId(b.id);
    setFormData({
      category_id: b.category_id.toString(),
      monthly_limit: b.monthly_limit.toString(),
      period: b.period || 'monthly'
    });
    setIsModalOpen(true);
  }

  async function handleDelete(id) {
    if (!confirm("Are you sure you want to delete this budget?")) return;
    try {
      await deleteRequest(`/api/budgets/${id}`);
      invalidateFinancialResources();
      loadData({ force: true });
    } catch (err) {
      alert("Error: " + err.message);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const limit = parseFloat(formData.monthly_limit);
    if (isNaN(limit) || limit <= 0) return alert("Enter a valid amount");
    if (!formData.category_id) return alert("Select a category");
    
    const payload = {
      category_id: parseInt(formData.category_id, 10),
      monthly_limit: limit,
      period: formData.period,
      currency: "USD",
      country: "US"
    };

    try {
      if (editingId) {
        await apiRequest(`/api/budgets/${editingId}`, {
          method: "PUT",
          body: payload
        });
      } else {
        await apiRequest("/api/budgets", {
          method: "POST",
          body: payload
        });
      }
      setIsModalOpen(false);
      invalidateFinancialResources();
      loadData({ force: true });
    } catch (err) {
      alert("Error: " + err.message);
    }
  }

  async function handleScanRecurring() {
    setScanningRecurring(true);
    setScanMessage("");
    try {
      const result = await apiRequest("/api/financial-tools/subscriptions/scan", {
        method: "POST"
      });
      invalidateFinancialResources();
      await loadData({ force: true });
      setScanMessage(result.detected ? `${result.detected} recurring item found.` : "No new recurring items found.");
      setActivePlannerTab("recurring");
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      setScanningRecurring(false);
    }
  }

  async function handleSubscriptionStatus(subscription, status) {
    try {
      if (status === "cancel_requested") {
        await apiRequest(`/api/financial-tools/subscriptions/${subscription.id}/cancel-request`, {
          method: "POST",
          body: { status, notes: "Requested from Planner" }
        });
      } else {
        await apiRequest(`/api/financial-tools/subscriptions/${subscription.id}`, {
          method: "PATCH",
          body: { status }
        });
      }
      invalidateFinancialResources();
      await loadData({ force: true });
    } catch (err) {
      alert("Error: " + err.message);
    }
  }

  if (loading) {
     return <div style={{ padding: "20px", textAlign: "center", color: "var(--text2)" }}>Loading planner...</div>;
  }

  const dashboardSummary = overview?.dashboard?.summary || {};
  const monthlySummary = overview?.monthlySummary || {};
  const trends = overview?.trends || [];
  const totalBudgetLimit = budgets.reduce((sum, b) => sum + (b.monthly_limit || 0), 0);
  const totalBudgetSpent = budgets.reduce((sum, b) => sum + (b.spent || 0), 0);
  const totalBudgetRemaining = Math.max(0, totalBudgetLimit - totalBudgetSpent);
  const budgetPct = totalBudgetLimit > 0 ? (totalBudgetSpent / totalBudgetLimit) * 100 : 0;
  const activeSubscriptions = subscriptions.filter(s => s.status === 'active');
  const managedSubscriptions = subscriptions.filter(s => s.status !== 'cancelled' && s.status !== 'ignored');
  const monthlySubscriptionCost = subscriptionSummary?.monthlyCost || activeSubscriptions.reduce((sum, s) => sum + (s.monthlyCost || s.amount || 0), 0);
  const projectedSavings = dashboardSummary.forecast_next_month ?? monthlySummary.savings ?? 0;
  const projectedIncome = trends.length ? trends.slice(-6).reduce((sum, item) => sum + (item.income || 0), 0) / Math.min(6, trends.length) : (monthlySummary.income || 0);
  const projectedExpenses = trends.length ? trends.slice(-6).reduce((sum, item) => sum + (item.expenses || 0), 0) / Math.min(6, trends.length) : (monthlySummary.expenses || 0);
  const forecastMax = Math.max(1, ...trends.slice(-6).flatMap(item => [item.income || 0, item.expenses || 0]));
  const riskBudgets = budgets.filter(b => b.percentage >= 80);

  const getIcon = (name) => {
    const n = name.toLowerCase();
    if (n.includes('hous') || n.includes('rent')) return <Home size={16} />;
    if (n.includes('groc')) return <ShoppingCart size={16} />;
    if (n.includes('din') || n.includes('food')) return <Pizza size={16} />;
    if (n.includes('trans') || n.includes('car') || n.includes('auto')) return <Car size={16} />;
    if (n.includes('entert') || n.includes('game')) return <Gamepad2 size={16} />;
    return <DollarSign size={16} />;
  };

  return (
    <>
      <div className="page-header">
        <div className="page-title">Planner</div>
        <div className="badge" style={{ fontSize: "11px", padding: "4px 12px" }}>Current Month</div>
      </div>
      
      <div className="nav-tabs">
        <button type="button" className={`nav-tab ${activePlannerTab === "budgets" ? "active" : ""}`} onClick={() => setActivePlannerTab("budgets")}>Budgets</button>
        <button type="button" className={`nav-tab ${activePlannerTab === "recurring" ? "active" : ""}`} onClick={() => setActivePlannerTab("recurring")}>Recurring</button>
        <button type="button" className={`nav-tab ${activePlannerTab === "forecast" ? "active" : ""}`} onClick={() => setActivePlannerTab("forecast")}>Forecast</button>
      </div>
      
      {activePlannerTab === "budgets" && (
        <>
          <div style={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--r2)", padding: "18px", marginBottom: "24px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "16px" }}>
              <div>
                <div className="small-label">Total Budget</div>
                <div style={{ fontFamily: "'Syne', sans-serif", fontSize: "24px", fontWeight: 700, color: "var(--text)" }}>{formatCurrency(totalBudgetLimit)}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="small-label">Spent</div>
                <div style={{ fontFamily: "'Syne', sans-serif", fontSize: "24px", fontWeight: 700, color: "var(--accent4)" }}>{formatCurrency(totalBudgetSpent)}</div>
              </div>
            </div>
            <div style={{ background: "var(--bg4)", borderRadius: "4px", height: "8px", overflow: "hidden" }}>
              <div style={{ width: `${Math.min(100, budgetPct)}%`, height: "100%", background: "linear-gradient(90deg, var(--accent3), var(--accent4))", borderRadius: "4px" }}></div>
            </div>
            <div style={{ fontSize: "11px", color: "var(--text3)", marginTop: "8px", fontWeight: 500 }}>{formatCurrency(totalBudgetRemaining)} remaining</div>
          </div>
          
          <div className="section-header" style={{ marginBottom: "16px" }}>
            <span className="section-title">Category Budgets</span>
            <button onClick={handleAdd} style={{ background: "var(--accent)", border: "none", borderRadius: "var(--r3)", padding: "6px 12px", fontSize: "11px", fontWeight: 700, color: "white", cursor: "pointer", display: "flex", alignItems: "center", gap: "4px" }}>
              <Plus size={14} /> New
            </button>
          </div>
          
          {budgets.map(b => (
            <div className="budget-item" key={b.id}>
              <div className="budget-header">
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span className="budget-name" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    {getIcon(b.category_name)} {b.category_name}
                  </span>
                  <div className="action-icons" style={{ marginLeft: "4px" }}>
                    <button className="action-icon" onClick={() => handleEdit(b)}><Pencil size={12} /></button>
                    <button className="action-icon danger" onClick={() => handleDelete(b.id)}><Trash2 size={12} /></button>
                  </div>
                </div>
                <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                  <span style={{ fontSize: "12px", color: "var(--text3)" }}>{formatCurrency(b.spent)}/{formatCurrency(b.monthly_limit)}</span>
                  <span className="budget-pct" style={{ color: b.percentage >= 100 ? "var(--accent5)" : "var(--accent4)" }}>{Math.round(b.percentage)}%</span>
                </div>
              </div>
              <div className="budget-bar-track">
                <div className="budget-bar-fill" style={{ width: `${Math.min(100, b.percentage)}%`, background: b.percentage >= 100 ? "var(--accent5)" : "var(--accent4)" }}></div>
              </div>
            </div>
          ))}
          {budgets.length === 0 && (
            <div style={{ textAlign: "center", padding: "20px", color: "var(--text3)" }}>No budgets set.</div>
          )}
        </>
      )}

      {activePlannerTab === "recurring" && (
        <>
          <div className="kpi-grid">
            <div className="kpi-card kpi-accent-blue">
              <div className="k-label">Active</div>
              <div className="k-val">{subscriptionSummary?.activeCount || activeSubscriptions.length}</div>
              <div className="k-change" style={{ color: "var(--text3)" }}>Recurring items</div>
            </div>
            <div className="kpi-card kpi-accent-red">
              <div className="k-label">Monthly Cost</div>
              <div className="k-val">{formatCurrency(monthlySubscriptionCost)}</div>
              <div className="k-change amount-neg">Projected outflow</div>
            </div>
          </div>

          <div className="section-header" style={{ marginBottom: "16px" }}>
            <span className="section-title">Recurring Bills</span>
            <button onClick={handleScanRecurring} disabled={scanningRecurring} style={{ background: "var(--accent)", border: "none", borderRadius: "var(--r3)", padding: "6px 12px", fontSize: "11px", fontWeight: 700, color: "white", cursor: "pointer", display: "flex", alignItems: "center", gap: "4px", opacity: scanningRecurring ? 0.7 : 1 }}>
              <RefreshCw size={14} /> {scanningRecurring ? "Scanning" : "Scan"}
            </button>
          </div>
          {scanMessage && <div className="profile-message" style={{ marginBottom: "14px" }}>{scanMessage}</div>}
          <div style={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--r2)", padding: "6px 14px", marginBottom: "16px" }}>
            {managedSubscriptions.map(sub => (
              <div className="tx-row" key={sub.id}>
                <div className="tx-icon" style={{ background: sub.status === "cancel_requested" ? "rgba(247,147,76,0.12)" : "rgba(242,78,116,0.12)" }}><CalendarClock size={16} /></div>
                <div className="tx-info">
                  <div className="tx-name">{sub.displayName}</div>
                  <div className="tx-meta">{sub.nextExpectedDate?.substring(5) || 'Upcoming'} · {sub.frequency} · {sub.status}</div>
                </div>
                <div className="tx-amount amount-neg" style={{ marginRight: "10px" }}>-{formatCurrency(sub.amount, sub.currency)}</div>
                <div className="action-icons">
                  {sub.status === "active" ? (
                    <button className="action-icon" title="Request cancellation" onClick={() => handleSubscriptionStatus(sub, "cancel_requested")}><XCircle size={14} /></button>
                  ) : (
                    <button className="action-icon" title="Mark active" onClick={() => handleSubscriptionStatus(sub, "active")}><CheckCircle2 size={14} /></button>
                  )}
                  <button className="action-icon danger" title="Ignore" onClick={() => handleSubscriptionStatus(sub, "ignored")}><Trash2 size={14} /></button>
                </div>
              </div>
            ))}
            {managedSubscriptions.length === 0 && (
              <div style={{ padding: "20px", textAlign: "center", color: "var(--text3)" }}>No recurring items detected yet.</div>
            )}
          </div>
        </>
      )}

      {activePlannerTab === "forecast" && (
        <>
          <div className="kpi-grid">
            <div className="kpi-card kpi-accent-green">
              <div className="k-label">Current Savings</div>
              <div className="k-val">{formatCurrency(monthlySummary.savings || 0)}</div>
              <div className="k-change" style={{ color: "var(--text3)" }}>This month</div>
            </div>
            <div className="kpi-card kpi-accent-purple">
              <div className="k-label">Next Month</div>
              <div className="k-val">{formatCurrency(projectedSavings)}</div>
              <div className="k-change amount-pos">Projected savings</div>
            </div>
          </div>

          <div style={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--r2)", padding: "18px", marginBottom: "20px" }}>
            <div className="section-header">
              <span className="section-title">Cashflow Forecast</span>
              <span className="badge"><TrendingUp size={12} style={{ verticalAlign: "middle" }} /> 6 mo</span>
            </div>
            <div className="bar-chart" style={{ height: "110px" }}>
              {trends.slice(-6).map(item => (
                <div key={item.month} style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: "5px" }}>
                  <div className="bar-row" style={{ height: "86px", alignItems: "flex-end" }}>
                    <div className="bar" style={{ height: `${Math.max(8, ((item.income || 0) / forecastMax) * 86)}px`, background: "var(--accent3)" }}></div>
                    <div className="bar" style={{ height: `${Math.max(8, ((item.expenses || 0) / forecastMax) * 86)}px`, background: "var(--accent5)" }}></div>
                  </div>
                  <div className="bar-label">{item.month?.substring(5, 7)}</div>
                </div>
              ))}
              {trends.length === 0 && (
                <div style={{ width: "100%", textAlign: "center", color: "var(--text3)", alignSelf: "center" }}>Add transactions to build a forecast.</div>
              )}
            </div>
          </div>

          <div style={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--r2)", padding: "6px 14px", marginBottom: "16px" }}>
            <div className="tx-row">
              <div className="tx-icon" style={{ background: "rgba(16,217,160,0.12)" }}><DollarSign size={16} /></div>
              <div className="tx-info">
                <div className="tx-name">Average monthly income</div>
                <div className="tx-meta">Based on recent transaction trends</div>
              </div>
              <div className="tx-amount amount-pos">{formatCurrency(projectedIncome)}</div>
            </div>
            <div className="tx-row">
              <div className="tx-icon" style={{ background: "rgba(242,78,116,0.12)" }}><ShoppingCart size={16} /></div>
              <div className="tx-info">
                <div className="tx-name">Average monthly expenses</div>
                <div className="tx-meta">Includes historical recurring spend</div>
              </div>
              <div className="tx-amount amount-neg">-{formatCurrency(projectedExpenses)}</div>
            </div>
            <div className="tx-row">
              <div className="tx-icon" style={{ background: "rgba(247,147,76,0.12)" }}><Film size={16} /></div>
              <div className="tx-info">
                <div className="tx-name">Known recurring outflow</div>
                <div className="tx-meta">{activeSubscriptions.length} active recurring items</div>
              </div>
              <div className="tx-amount amount-neg">-{formatCurrency(monthlySubscriptionCost)}</div>
            </div>
          </div>

          {riskBudgets.length > 0 && (
            <div className="processing-pill">
              <div className="pulse"></div>{riskBudgets.length} budget {riskBudgets.length === 1 ? "needs" : "need"} attention this month
            </div>
          )}
        </>
      )}

      <Modal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} title={editingId ? "Edit Budget" : "New Budget"}>
        <form onSubmit={handleSubmit}>
          <div className="modal-form-group">
            <label className="modal-form-label">Category</label>
            <select className="modal-select" required value={formData.category_id} onChange={e => setFormData({...formData, category_id: e.target.value})}>
              <option value="" disabled>Select a category...</option>
              {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div className="modal-form-group">
            <label className="modal-form-label">Monthly Limit</label>
            <input type="number" step="0.01" required className="modal-input" placeholder="0.00" value={formData.monthly_limit} onChange={e => setFormData({...formData, monthly_limit: e.target.value})} />
          </div>
          <div className="modal-form-group">
            <label className="modal-form-label">Period</label>
            <select className="modal-select" value={formData.period} onChange={e => setFormData({...formData, period: e.target.value})}>
              <option value="monthly">Monthly</option>
              <option value="weekly">Weekly</option>
            </select>
          </div>
          <div className="modal-actions">
            <button type="button" className="modal-btn modal-btn-cancel" onClick={() => setIsModalOpen(false)}>Cancel</button>
            <button type="submit" className="modal-btn modal-btn-submit">Save Budget</button>
          </div>
        </form>
      </Modal>
    </>
  );
}
