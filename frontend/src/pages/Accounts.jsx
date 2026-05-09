import { useState, useEffect } from "react";
import { Landmark } from 'lucide-react';
import { apiRequest } from "../lib/api";
import { formatCurrency, formatDate } from "../lib/format";
import { loadCachedResource, readCachedResource, invalidateFinancialResources } from "../lib/resourceCache";

export default function Accounts() {
  const [accounts, setAccounts] = useState(() => readCachedResource("accounts")?.accounts || []);
  const [loading, setLoading] = useState(() => !readCachedResource("accounts"));
  
  async function loadData(options = {}) {
    try {
      const data = await loadCachedResource("accounts", options);
      setAccounts(data.accounts || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  async function handleLink() {
    try {
      await apiRequest("/api/banks/connect", {
        method: "POST",
        body: { provider: "mock", country: "US", public_token: "mock-token-123" }
      });
      invalidateFinancialResources();
      loadData({ force: true });
    } catch (err) {
      alert("Failed to connect: " + err.message);
    }
  }

  const totalBalance = accounts.reduce((sum, acc) => sum + (acc.balance || 0), 0);

  if (loading) {
     return <div style={{ padding: "20px", textAlign: "center", color: "var(--text2)" }}>Loading accounts...</div>;
  }

  return (
    <>
      <div className="page-header">
        <div className="page-title">Accounts</div>
        <button onClick={handleLink} style={{ background: "var(--accent)", border: "none", borderRadius: "var(--r3)", padding: "8px 14px", fontSize: "12px", fontWeight: 700, color: "white", cursor: "pointer" }}>+ Link Mock Bank</button>
      </div>
      
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "20px", background: "var(--bg3)", borderRadius: "var(--r2)", padding: "16px", border: "1px solid var(--border)" }}>
        <div>
          <div className="small-label" style={{ marginBottom: "4px" }}>Total Balance</div>
          <div style={{ fontFamily: "'Syne', sans-serif", fontSize: "28px", fontWeight: 800, color: "var(--text)" }}>{formatCurrency(totalBalance)}</div>
        </div>
        <div className="badge badge-success">↑ Healthy</div>
      </div>
      
      <div className="bank-grid">
        {accounts.map(acc => (
          <div key={acc.id} className="bank-card bank-card-chase">
            <div className="card-logo"><Landmark size={16} style={{ display: "inline", verticalAlign: "middle", marginRight: "4px" }} /> {acc.institutionName || acc.provider}</div>
            <div className="card-chip"></div>
            <div className="card-number">•••• •••• •••• {acc.mask || '0000'}</div>
            <div className="card-name">{acc.name || "Account"}</div>
            <div className="card-balance">{formatCurrency(acc.balance, acc.currency)}</div>
            <div style={{ position: "absolute", bottom: "20px", left: "20px", fontSize: "10px", color: "rgba(255,255,255,0.5)", display: "flex", alignItems: "center", gap: "5px" }}>
              <div style={{ width: "6px", height: "6px", background: "#2ecc71", borderRadius: "50%" }}></div>Synced {acc.lastSyncedAt ? formatDate(acc.lastSyncedAt) : 'recently'}
            </div>
          </div>
        ))}
        {accounts.length === 0 && (
          <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: "40px", color: "var(--text3)" }}>No accounts connected yet.</div>
        )}
      </div>
    </>
  );
}
