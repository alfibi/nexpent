import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { ShoppingCart, Bell, CircleDollarSign, ArrowRight } from 'lucide-react';
import { formatCurrency, formatPercent, formatDate } from "../lib/format";
import { useAuth } from "../contexts/AuthContext.jsx";
import { useNotifications } from "../contexts/NotificationContext.jsx";
import { loadCachedResource, readCachedResource } from "../lib/resourceCache";

export default function Dashboard() {
  const { user } = useAuth();
  const { notifications, unreadCount, permission, requestPermission, markAllRead, refreshNotifications } = useNotifications();
  const [data, setData] = useState(() => readCachedResource("dashboardOverview"));
  const [loading, setLoading] = useState(() => !readCachedResource("dashboardOverview"));
  const [notificationsOpen, setNotificationsOpen] = useState(false);

  useEffect(() => {
    let ignore = false;

    async function loadData() {
      try {
        const overview = await loadCachedResource("dashboardOverview");
        if (!ignore) {
          setData(overview);
        }
      } catch (err) {
        console.error("Failed to load dashboard data", err);
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }
    loadData();
    return () => {
      ignore = true;
    };
  }, []);

  if (loading || !data) {
    return <div style={{ padding: "20px", textAlign: "center", color: "var(--text2)" }}>Loading dashboard...</div>;
  }

  const { dashboard, trends } = data;
  const summary = dashboard?.summary || {};

  async function handleNotificationsClick() {
    setNotificationsOpen((open) => !open);
    markAllRead();
    void refreshNotifications();
    if (permission === "default") {
      await requestPermission();
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <div style={{ fontSize: "12px", color: "var(--text3)", marginBottom: "2px" }}>Good morning,</div>
          <div className="page-title">{user?.profile?.full_name || user?.username || "User"}</div>
        </div>
        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          <button type="button" className="notification-button" onClick={handleNotificationsClick} aria-label="Open notifications">
            <Bell size={17} />
            {unreadCount > 0 && (
              <span className="notification-dot">{unreadCount > 9 ? "9+" : unreadCount}</span>
            )}
          </button>
          <Link to="/profile" className="avatar" aria-label="Open profile">{(user?.username || "U").substring(0, 2).toUpperCase()}</Link>
        </div>
      </div>

      {notificationsOpen && (
        <div className="notification-panel">
          <div className="notification-panel-header">
            <div>
              <div className="section-title">Notifications</div>
              <div className="small-label">
                {permission === "granted"
                  ? "Browser alerts enabled"
                  : permission === "denied"
                    ? "Browser alerts blocked"
                    : "Tap bell to enable browser alerts"}
              </div>
            </div>
            <button type="button" className="see-all" onClick={() => void refreshNotifications({ force: true })}>Refresh</button>
          </div>
          {notifications.length > 0 ? (
            notifications.map((item) => (
              <Link to={item.actionPath || "/advisor"} className={`notification-item notification-${item.severity}`} key={item.id}>
                <div>
                  <div className="notification-title">{item.title}</div>
                  <div className="notification-message">{item.message}</div>
                  <div className="notification-source">{item.source}</div>
                </div>
                <span className="notification-severity">{item.severity}</span>
              </Link>
            ))
          ) : (
            <div className="notification-empty">No urgent money alerts right now.</div>
          )}
        </div>
      )}
      
      <div className="kpi-grid">
        <div className="kpi-card kpi-accent-green">
          <div className="k-label">Net Balance</div>
          <div className="k-val">{formatCurrency(summary.total_balance || 0)}</div>
          <div className="k-change amount-pos">Total available</div>
        </div>
        <div className="kpi-card kpi-accent-blue">
          <div className="k-label">Monthly Income</div>
          <div className="k-val">{formatCurrency(summary.monthly_income || 0)}</div>
          <div className="k-change" style={{ color: "var(--text3)" }}>This Month</div>
        </div>
        <div className="kpi-card kpi-accent-red">
          <div className="k-label">Monthly Expenses</div>
          <div className="k-val">{formatCurrency(Math.abs(summary.monthly_expenses || 0))}</div>
          <div className="k-change amount-neg">This Month</div>
        </div>
        <div className="kpi-card kpi-accent-purple">
          <div className="k-label">Savings Rate</div>
          <div className="k-val">{formatPercent(summary.savings_rate || 0)}</div>
          <div className="k-change amount-pos">Current rate</div>
        </div>
      </div>
      
      <div className="glass-card" style={{ marginBottom: "16px" }}>
        <div className="section-header">
          <span className="section-title">Cashflow Trend</span>
          <span className="badge">6 months</span>
        </div>
        <div style={{ display: "flex", gap: "4px", alignItems: "flex-end", height: "80px" }}>
          {trends && trends.slice(-6).map((item, idx) => {
            const maxValue = Math.max(1, ...trends.map(t => Math.max(t.income, Math.abs(t.expenses))));
            const incHeight = Math.max(10, (item.income / maxValue) * 100);
            const expHeight = Math.max(10, (Math.abs(item.expenses) / maxValue) * 100);
            return (
              <div key={item.month} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: "2px" }}>
                <div style={{ flex: 1, width: "100%", background: "var(--bg4)", borderRadius: "4px 4px 0 0", display: "flex", alignItems: "flex-end", position: "relative" }}>
                   <div style={{ width: "50%", height: `${incHeight}%`, background: "var(--accent-green)", borderRadius: "4px 4px 0 0", position: "absolute", left: 0, bottom: 0, opacity: 0.8 }}></div>
                   <div style={{ width: "50%", height: `${expHeight}%`, background: "var(--accent-red)", borderRadius: "4px 4px 0 0", position: "absolute", right: 0, bottom: 0, opacity: 0.8 }}></div>
                </div>
                <div className="bar-label">{item.month.substring(5, 7)}</div>
              </div>
            );
          })}
        </div>
      </div>
      
      <div className="section-header">
        <span className="section-title">Recent Activity</span>
        <Link to="/ledger" className="see-all">See all <ArrowRight size={14} style={{ display: "inline", verticalAlign: "middle" }} /></Link>
      </div>
      
      <div style={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--r2)", padding: "6px 14px" }}>
        {dashboard?.recent_activity?.length > 0 ? (
          dashboard.recent_activity.map(item => (
            <div className="tx-row" key={`${item.id}-${item.date}`}>
              <div className="tx-icon" style={{ background: item.transaction_type === 'income' ? "rgba(16,217,160,0.12)" : "rgba(79,142,247,0.15)" }}>
                {item.transaction_type === 'income' ? <CircleDollarSign size={16} /> : <ShoppingCart size={16} />}
              </div>
              <div className="tx-info">
                <div className="tx-name">{item.primary_label}</div>
                <div className="tx-meta">{item.secondary_label} · {formatDate(item.date)}</div>
              </div>
              <div className={`tx-amount ${item.transaction_type === 'income' ? 'amount-pos' : 'amount-neg'}`}>
                {item.transaction_type === 'income' ? '+' : ''}{formatCurrency(item.amount)}
              </div>
            </div>
          ))
        ) : (
          <div style={{ padding: "10px 0", color: "var(--text3)", fontSize: "14px" }}>No recent activity found.</div>
        )}
      </div>
      
      <div className="fab">
        <Link to="/ledger" className="fab-btn" style={{ textDecoration: "none", color: "inherit" }}>＋ Add Transaction</Link>
      </div>
    </>
  );
}
