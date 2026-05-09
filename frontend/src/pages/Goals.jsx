import { useState, useEffect } from "react";
import { Palmtree, CreditCard, Landmark, Target, Pencil, Trash2 } from 'lucide-react';
import { apiRequest, deleteRequest } from "../lib/api";
import { formatCurrency } from "../lib/format";
import Modal from "../components/Modal";
import { invalidateFinancialResources, loadCachedResource, readCachedResource } from "../lib/resourceCache";

export default function Goals() {
  const [goals, setGoals] = useState(() => readCachedResource("goals")?.goals || []);
  const [loading, setLoading] = useState(() => !readCachedResource("goals"));

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    targetAmount: '',
    currentAmount: '0',
    targetDate: ''
  });

  async function loadData(options = {}) {
    try {
      const data = await loadCachedResource("goals", options);
      setGoals(data.goals || []);
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
      name: '',
      targetAmount: '',
      currentAmount: '0',
      targetDate: ''
    });
    setIsModalOpen(true);
  }

  function handleEdit(g) {
    setEditingId(g.id);
    setFormData({
      name: g.name,
      targetAmount: g.targetAmount.toString(),
      currentAmount: g.currentAmount.toString(),
      targetDate: g.targetDate ? g.targetDate.substring(0, 10) : ''
    });
    setIsModalOpen(true);
  }

  async function handleDelete(id) {
    if (!confirm("Are you sure you want to delete this goal?")) return;
    try {
      await deleteRequest(`/api/goals/${id}`);
      invalidateFinancialResources();
      loadData({ force: true });
    } catch (err) {
      alert("Error: " + err.message);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const tAmt = parseFloat(formData.targetAmount);
    const cAmt = parseFloat(formData.currentAmount) || 0;
    
    if (isNaN(tAmt) || tAmt <= 0) return alert("Enter a valid target amount");
    if (!formData.name) return alert("Enter a goal name");

    const payload = {
      name: formData.name,
      targetAmount: tAmt,
      currentAmount: cAmt,
      currency: "USD",
      country: "US",
      targetDate: formData.targetDate || null
    };

    try {
      if (editingId) {
        await apiRequest(`/api/goals/${editingId}`, {
          method: "PUT",
          body: payload
        });
      } else {
        await apiRequest("/api/goals", {
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

  const renderCircle = (percent, color) => {
    const dash = 163.4;
    const offset = Math.max(0, dash - (percent / 100) * dash);
    return (
      <svg width="60" height="60" viewBox="0 0 60 60" style={{ margin: "0 auto 12px", display: "block" }}>
        <circle cx="30" cy="30" r="26" fill="none" stroke={`${color}33`} strokeWidth="5" />
        <circle cx="30" cy="30" r="26" fill="none" stroke={color} strokeWidth="5" strokeDasharray={dash} strokeDashoffset={offset} strokeLinecap="round" transform="rotate(-90 30 30)" />
        <text x="30" y="35" textAnchor="middle" fill={color} fontSize="13" fontWeight="700" fontFamily="Syne,sans-serif">{Math.round(percent)}%</text>
      </svg>
    );
  };

  const colors = ["#4F8EF7", "#10D9A0", "#F7934C", "#7C3AED"];

  if (loading) {
     return <div style={{ padding: "20px", textAlign: "center", color: "var(--text2)" }}>Loading goals...</div>;
  }

  return (
    <>
      <div className="page-header">
        <div className="page-title">Goals</div>
        <button onClick={handleAdd} style={{ background: "var(--accent)", border: "none", borderRadius: "var(--r3)", padding: "8px 14px", fontSize: "12px", fontWeight: 700, color: "white", cursor: "pointer" }}>+ New Goal</button>
      </div>
      
      <div className="goal-grid">
        {goals.map((g, i) => {
          const color = colors[i % colors.length];
          return (
            <div className="goal-card-wrapper" key={g.id} style={{ position: "relative", background: `linear-gradient(135deg, ${color}26, ${color}0D)`, border: `1px solid ${color}33`, borderRadius: "var(--r2)", padding: "20px 16px", textAlign: "center", marginBottom: "16px" }}>
              <div className="action-icons" style={{ position: "absolute", top: "10px", right: "10px" }}>
                <button className="action-icon" onClick={() => handleEdit(g)}><Pencil size={12} /></button>
                <button className="action-icon danger" onClick={() => handleDelete(g.id)}><Trash2 size={12} /></button>
              </div>
              {renderCircle(g.progressPercentage, color)}
              <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}>{g.name}</div>
              <div style={{ fontSize: "11px", color: "var(--text3)", marginTop: "4px" }}>{formatCurrency(g.currentAmount)} / {formatCurrency(g.targetAmount)}</div>
            </div>
          );
        })}
        {goals.length === 0 && (
          <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: "40px", color: "var(--text3)" }}>No goals set.</div>
        )}
      </div>
      
      <div className="section-title" style={{ marginBottom: "16px" }}>Financial Calculators</div>
      
      <div style={{ display: "flex", gap: "12px" }}>
        <div style={{ flex: 1, background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--r2)", padding: "20px 14px", textAlign: "center", cursor: "pointer" }}>
          <div style={{ fontSize: "28px", marginBottom: "8px", display: "flex", justifyContent: "center" }}><Landmark size={24} /></div>
          <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}>Compound Interest</div>
          <div style={{ fontSize: "11px", color: "var(--text3)", marginTop: "4px" }}>Grow your savings</div>
        </div>
        <div style={{ flex: 1, background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--r2)", padding: "20px 14px", textAlign: "center", cursor: "pointer" }}>
          <div style={{ fontSize: "28px", marginBottom: "8px", display: "flex", justifyContent: "center" }}><CreditCard size={24} /></div>
          <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}>Loan Payoff</div>
          <div style={{ fontSize: "11px", color: "var(--text3)", marginTop: "4px" }}>Clear your debt</div>
        </div>
      </div>

      <Modal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} title={editingId ? "Edit Goal" : "New Goal"}>
        <form onSubmit={handleSubmit}>
          <div className="modal-form-group">
            <label className="modal-form-label">Goal Name</label>
            <input type="text" required className="modal-input" placeholder="E.g. Emergency Fund, New Car" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} />
          </div>
          <div className="modal-form-group">
            <label className="modal-form-label">Target Amount</label>
            <input type="number" step="0.01" required className="modal-input" placeholder="0.00" value={formData.targetAmount} onChange={e => setFormData({...formData, targetAmount: e.target.value})} />
          </div>
          <div className="modal-form-group">
            <label className="modal-form-label">Current Amount</label>
            <input type="number" step="0.01" className="modal-input" placeholder="0.00" value={formData.currentAmount} onChange={e => setFormData({...formData, currentAmount: e.target.value})} />
          </div>
          <div className="modal-form-group">
            <label className="modal-form-label">Target Date (Optional)</label>
            <input type="date" className="modal-input" value={formData.targetDate} onChange={e => setFormData({...formData, targetDate: e.target.value})} />
          </div>
          <div className="modal-actions">
            <button type="button" className="modal-btn modal-btn-cancel" onClick={() => setIsModalOpen(false)}>Cancel</button>
            <button type="submit" className="modal-btn modal-btn-submit">Save Goal</button>
          </div>
        </form>
      </Modal>
    </>
  );
}
