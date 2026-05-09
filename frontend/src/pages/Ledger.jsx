import { useState, useEffect, useDeferredValue, useMemo } from "react";
import { AlertTriangle, CheckCircle2, CircleDollarSign, Pencil, Plus, Receipt, Search, ShoppingCart, Trash2, Upload } from 'lucide-react';
import { apiRequest, deleteRequest } from "../lib/api";
import { formatCurrency, formatDate } from "../lib/format";
import { getAppSettings } from "../lib/settings";
import Modal from "../components/Modal";
import { invalidateFinancialResources, loadCachedResource, readCachedResource } from "../lib/resourceCache";

export default function Ledger() {
  const [transactions, setTransactions] = useState(() => readCachedResource("transactions")?.transactions || []);
  const [receipts, setReceipts] = useState(() => readCachedResource("receipts")?.receipts || []);
  const [loading, setLoading] = useState(() => !readCachedResource("transactions"));
  const [receiptsLoading, setReceiptsLoading] = useState(() => !readCachedResource("receipts"));
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [ledgerMode, setLedgerMode] = useState("transactions");
  const [activeTab, setActiveTab] = useState("All");
  const [receiptFile, setReceiptFile] = useState(null);
  const [scanningReceipt, setScanningReceipt] = useState(false);
  const [receiptData, setReceiptData] = useState(null);
  const [appSettings, setAppSettings] = useState(() => getAppSettings());

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [formData, setFormData] = useState({
    type: 'Expense',
    amount: '',
    merchant: '',
    category: 'Uncategorized',
    date: new Date().toISOString().substring(0, 10),
    description: ''
  });

  async function loadData(options = {}) {
    try {
      const data = await loadCachedResource("transactions", options);
      setTransactions(data.transactions || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function loadReceipts(options = {}) {
    try {
      const data = await loadCachedResource("receipts", options);
      setReceipts(data.receipts || []);
    } catch (err) {
      console.error(err);
    } finally {
      setReceiptsLoading(false);
    }
  }

  useEffect(() => {
    setAppSettings(getAppSettings());
    loadData();
    loadReceipts();
  }, []);

  function handleAdd() {
    setEditingId(null);
    setFormData({
      type: 'Expense',
      amount: '',
      merchant: '',
      category: 'Uncategorized',
      date: new Date().toISOString().substring(0, 10),
      description: ''
    });
    setIsModalOpen(true);
  }

  function handleEdit(t) {
    setEditingId(t.id);
    setFormData({
      type: t.amount >= 0 ? 'Income' : 'Expense',
      amount: Math.abs(t.amount).toString(),
      merchant: t.merchant || '',
      category: t.category || 'Uncategorized',
      date: t.date ? t.date.substring(0, 10) : new Date().toISOString().substring(0, 10),
      description: t.description || ''
    });
    setIsModalOpen(true);
  }

  async function handleDelete(id) {
    if (!confirm("Are you sure you want to delete this transaction?")) return;
    try {
      await deleteRequest(`/api/transactions/${id}`);
      invalidateFinancialResources();
      loadData({ force: true });
    } catch (err) {
      alert("Error: " + err.message);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const val = parseFloat(formData.amount);
    if (isNaN(val) || val <= 0) return alert("Enter a valid amount");
    
    const amountToSend = formData.type === 'Expense' ? -val : val;
    
    const payload = {
      amount: amountToSend,
      currency: appSettings.defaultCurrency,
      country: appSettings.defaultCountry,
      merchant: formData.merchant,
      category: formData.category,
      date: formData.date,
      description: formData.description,
      source: "manual"
    };

    try {
      if (editingId) {
        await apiRequest(`/api/transactions/${editingId}`, {
          method: "PUT",
          body: payload
        });
      } else {
        await apiRequest("/api/transactions", {
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

  async function handleReceiptScan(e) {
    e.preventDefault();
    if (!receiptFile) return;

    setScanningReceipt(true);
    setReceiptData(null);
    try {
      const scanData = new FormData();
      scanData.append("file", receiptFile);
      scanData.append("country", appSettings.defaultCountry);
      scanData.append("currency", appSettings.defaultCurrency);

      const res = await apiRequest("/api/receipts/upload", {
        method: "POST",
        body: scanData
      });
      setReceiptData(res);
      setReceiptFile(null);
      invalidateFinancialResources();
      await Promise.all([loadData({ force: true }), loadReceipts({ force: true })]);
    } catch (err) {
      alert("Failed to scan receipt: " + err.message);
    } finally {
      setScanningReceipt(false);
    }
  }

  const filteredTransactions = useMemo(() => {
    const normalizedSearch = deferredSearch.trim().toLowerCase();
    return transactions.filter(t => {
      const matchesSearch = !normalizedSearch ||
                            t.merchant?.toLowerCase().includes(normalizedSearch) || 
                            t.description?.toLowerCase().includes(normalizedSearch) ||
                            t.category?.toLowerCase().includes(normalizedSearch);
    
      if (!matchesSearch) return false;
    
      if (activeTab === "Income") return t.amount > 0;
      if (activeTab === "Expenses") return t.amount < 0;
      return true;
    });
  }, [activeTab, deferredSearch, transactions]);

  const { totalIncome, totalExpense } = useMemo(() => {
    return transactions.reduce(
      (totals, t) => {
        if (t.amount > 0) {
          totals.totalIncome += t.amount;
        } else if (t.amount < 0) {
          totals.totalExpense += t.amount;
        }
        return totals;
      },
      { totalIncome: 0, totalExpense: 0 }
    );
  }, [transactions]);

  const { grouped, sortedDates } = useMemo(() => {
    const nextGrouped = filteredTransactions.reduce((acc, t) => {
      const d = t.date.substring(0, 10);
      if (!acc[d]) acc[d] = [];
      acc[d].push(t);
      return acc;
    }, {});

    return {
      grouped: nextGrouped,
      sortedDates: Object.keys(nextGrouped).sort((a, b) => new Date(b) - new Date(a))
    };
  }, [filteredTransactions]);

  return (
    <>
      <div className="page-header">
        <div className="page-title">Ledger</div>
        <div style={{ display: "flex", gap: "8px" }}>
          <button onClick={() => setLedgerMode("receipts")} style={{ background: "var(--bg3)", border: "1px solid var(--border2)", borderRadius: "var(--r3)", padding: "8px 14px", fontSize: "12px", fontWeight: 700, color: "var(--text2)", cursor: "pointer", display: "flex", alignItems: "center", gap: "4px" }}>
            <Receipt size={14} /> Receipt
          </button>
          <button onClick={handleAdd} style={{ background: "var(--accent)", border: "none", borderRadius: "var(--r3)", padding: "8px 14px", fontSize: "12px", fontWeight: 700, color: "white", cursor: "pointer", display: "flex", alignItems: "center", gap: "4px" }}>
            <Plus size={14} /> New
          </button>
        </div>
      </div>

      <div className="nav-tabs">
        <button type="button" className={`nav-tab ${ledgerMode === "transactions" ? "active" : ""}`} onClick={() => setLedgerMode("transactions")}>Transactions</button>
        <button type="button" className={`nav-tab ${ledgerMode === "receipts" ? "active" : ""}`} onClick={() => setLedgerMode("receipts")}>Receipts</button>
      </div>
      
      {ledgerMode === "transactions" ? (
        <>
          <div className="search-bar">
            <div className="search-icon"><Search size={16} /></div>
            <input 
              type="text" 
              className="search-text" 
              placeholder="Search transactions…" 
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          
          <div className="filter-row">
            <div className={`filter-chip ${activeTab === 'All' ? 'active' : ''}`} onClick={() => setActiveTab('All')}>All</div>
            <div className={`filter-chip ${activeTab === 'Income' ? 'active' : ''}`} onClick={() => setActiveTab('Income')}>Income</div>
            <div className={`filter-chip ${activeTab === 'Expenses' ? 'active' : ''}`} onClick={() => setActiveTab('Expenses')}>Expenses</div>
          </div>
          
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "16px", background: "var(--bg3)", borderRadius: "var(--r3)", padding: "12px 16px", border: "1px solid var(--border)" }}>
            <div style={{ fontSize: "12px", color: "var(--text3)" }}>{filteredTransactions.length} transactions</div>
            <div style={{ display: "flex", gap: "16px" }}>
              <div style={{ fontSize: "12px", fontWeight: 600 }}><span style={{ color: "var(--accent-green)" }}>↑ {formatCurrency(totalIncome)}</span></div>
              <div style={{ fontSize: "12px", fontWeight: 600 }}><span style={{ color: "var(--accent-red)" }}>↓ {formatCurrency(Math.abs(totalExpense))}</span></div>
            </div>
          </div>
          
          {loading && <div style={{ padding: "20px", textAlign: "center", color: "var(--text2)" }}>Loading...</div>}

          {sortedDates.map(date => (
            <div key={date}>
              <div style={{ fontSize: "11px", fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "10px" }}>{formatDate(date)}</div>
              <div style={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--r2)", padding: "6px 14px", marginBottom: "16px" }}>
                {grouped[date].map(t => (
                   <div className="tx-row" key={t.id}>
                     <div className="tx-icon" style={{ background: t.amount >= 0 ? "rgba(16,217,160,0.12)" : "rgba(79,142,247,0.15)" }}>
                       {t.amount >= 0 ? <CircleDollarSign size={16} /> : <ShoppingCart size={16} />}
                     </div>
                     <div className="tx-info">
                       <div className="tx-name">{t.merchant || t.primary_label || t.description || 'Unknown'}</div>
                       <div className="tx-meta">{t.category} · {t.source}</div>
                     </div>
                     <div className={`tx-amount ${t.amount >= 0 ? 'amount-pos' : 'amount-neg'}`} style={{ marginRight: "12px" }}>
                       {t.amount >= 0 ? '+' : ''}{formatCurrency(t.amount)}
                     </div>
                     <div className="action-icons">
                       <button className="action-icon" onClick={() => handleEdit(t)}><Pencil size={14} /></button>
                       <button className="action-icon danger" onClick={() => handleDelete(t.id)}><Trash2 size={14} /></button>
                     </div>
                   </div>
                ))}
              </div>
            </div>
          ))}
          
          {!loading && sortedDates.length === 0 && (
             <div style={{ textAlign: "center", padding: "40px", color: "var(--text3)" }}>No transactions found.</div>
          )}
        </>
      ) : (
        <div className="ledger-receipts">
          <form className="receipt-upload" onSubmit={handleReceiptScan}>
            <div style={{ fontSize: "32px", marginBottom: "12px" }}><Upload size={28} /></div>
            <div style={{ fontSize: "14px", fontWeight: 600, color: "var(--text2)", marginBottom: "4px" }}>Select a receipt</div>
            <div style={{ fontSize: "12px", color: "var(--text3)", marginBottom: "16px" }}>Images, PDFs, and text files can be scanned into Ledger expenses</div>
            <input type="file" accept="image/*,.pdf,.txt" onChange={e => setReceiptFile(e.target.files?.[0] || null)} style={{ display: 'block', margin: '0 auto 10px', fontSize: "12px" }} />
            <button disabled={!receiptFile || scanningReceipt} type="submit" style={{ background: "linear-gradient(135deg, var(--accent), var(--accent2))", border: "none", borderRadius: "var(--r3)", padding: "10px 20px", fontSize: "13px", fontWeight: 700, color: "white", cursor: "pointer", opacity: (!receiptFile || scanningReceipt) ? 0.6 : 1 }}>
               {scanningReceipt ? "Scanning..." : "Scan & Add Expense"}
            </button>
          </form>
          
          {scanningReceipt && (
            <div className="processing-pill" style={{ marginTop: "16px" }}>
              <div className="pulse"></div>Processing receipt with AI...
            </div>
          )}
          
          {receiptData && (
            <div style={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--r2)", padding: "16px", marginTop: "24px" }}>
              <div style={{ fontSize: "12px", fontWeight: 700, color: receiptData.transaction ? "var(--accent3)" : "var(--accent4)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "12px", display: "flex", alignItems: "center", gap: "6px" }}>
                {receiptData.transaction ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
                {receiptData.transaction ? "Added to Ledger" : "Needs Review"}
              </div>
              <div style={{ display: "flex", gap: "16px" }}>
                <div style={{ flex: "0 0 80px", background: "var(--bg4)", borderRadius: "var(--r3)", height: "90px", display: "flex", alignItems: "center", justifyContent: "center" }}><Receipt size={32} /></div>
                <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", gap: "8px" }}>
                  <div>
                    <div style={{ fontSize: "11px", color: "var(--text3)" }}>Merchant</div>
                    <div style={{ fontSize: "14px", fontWeight: 600, color: "var(--text)" }}>{receiptData.merchant || 'Unknown'}</div>
                  </div>
                  <div style={{ display: "flex", gap: "24px", flexWrap: "wrap" }}>
                    <div>
                      <div style={{ fontSize: "11px", color: "var(--text3)" }}>Amount</div>
                      <div style={{ fontSize: "14px", fontWeight: 600, color: "var(--accent3)" }}>{formatCurrency(receiptData.amount || 0, receiptData.currency)}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: "11px", color: "var(--text3)" }}>Category</div>
                      <div style={{ fontSize: "14px", fontWeight: 600, color: "var(--text)" }}>{receiptData.transaction?.category || receiptData.items?.[0]?.category || 'Uncategorized'}</div>
                    </div>
                  </div>
                </div>
              </div>
              {receiptData.items?.length > 0 && (
                <div style={{ marginTop: "14px", borderTop: "1px solid var(--border)", paddingTop: "12px" }}>
                  {receiptData.items.slice(0, 4).map(item => (
                    <div key={item.id || item.name} style={{ display: "flex", justifyContent: "space-between", gap: "12px", fontSize: "12px", color: "var(--text2)", padding: "4px 0" }}>
                      <span>{item.name}</span>
                      <span style={{ color: "var(--text)", fontWeight: 600 }}>{formatCurrency(item.totalPrice || 0, receiptData.currency)}</span>
                    </div>
                  ))}
                </div>
              )}
              {!receiptData.transaction && (
                <div style={{ marginTop: "12px", fontSize: "12px", color: "var(--text3)", lineHeight: 1.5 }}>
                  OCR saved the receipt, but no expense was created because the total could not be read.
                </div>
              )}
              <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
                <button onClick={() => setLedgerMode("transactions")} style={{ flex: 1, background: "var(--accent)", border: "none", borderRadius: "var(--r3)", padding: "12px", fontSize: "13px", fontWeight: 700, color: "white", cursor: "pointer" }}>
                   View Transactions
                </button>
                <button onClick={() => setReceiptData(null)} style={{ flex: 1, background: "transparent", border: "1px solid var(--border2)", borderRadius: "var(--r3)", padding: "12px", fontSize: "13px", color: "var(--text2)", cursor: "pointer", fontWeight: 600 }}>Done</button>
              </div>
            </div>
          )}

          <div className="section-header" style={{ marginTop: "24px" }}>
            <span className="section-title">Recent Receipts</span>
            <span className="badge">{receipts.length}</span>
          </div>

          {receiptsLoading && <div style={{ padding: "20px", textAlign: "center", color: "var(--text2)" }}>Loading receipts...</div>}

          {!receiptsLoading && receipts.length === 0 && (
            <div style={{ textAlign: "center", padding: "32px", color: "var(--text3)", background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--r2)" }}>No receipts scanned yet.</div>
          )}

          {receipts.length > 0 && (
            <div style={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "var(--r2)", padding: "6px 14px" }}>
              {receipts.map(receipt => (
                <div className="tx-row" key={receipt.id}>
                  <div className="tx-icon" style={{ background: receipt.transaction ? "rgba(16,217,160,0.12)" : "rgba(247,147,76,0.12)" }}>
                    <Receipt size={16} />
                  </div>
                  <div className="tx-info">
                    <div className="tx-name">{receipt.merchant || "Unknown merchant"}</div>
                    <div className="tx-meta">{receipt.date ? formatDate(receipt.date) : "No date"} · {receipt.status || "saved"}</div>
                  </div>
                  <div className={`tx-amount ${receipt.transaction ? "amount-neg" : ""}`}>
                    {formatCurrency(receipt.amount || 0, receipt.currency)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <Modal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} title={editingId ? "Edit Transaction" : "New Transaction"}>
        <form onSubmit={handleSubmit}>
          <div className="modal-form-group">
            <label className="modal-form-label">Type</label>
            <select className="modal-select" value={formData.type} onChange={e => setFormData({...formData, type: e.target.value})}>
              <option value="Expense">Expense</option>
              <option value="Income">Income</option>
            </select>
          </div>
          <div className="modal-form-group">
            <label className="modal-form-label">Amount</label>
            <input type="number" step="0.01" required className="modal-input" placeholder="0.00" value={formData.amount} onChange={e => setFormData({...formData, amount: e.target.value})} />
          </div>
          <div className="modal-form-group">
            <label className="modal-form-label">Merchant / Title</label>
            <input type="text" required className="modal-input" placeholder="E.g. Walmart, Salary..." value={formData.merchant} onChange={e => setFormData({...formData, merchant: e.target.value})} />
          </div>
          <div className="modal-form-group">
            <label className="modal-form-label">Category</label>
            <input type="text" className="modal-input" placeholder="E.g. Groceries, Income" value={formData.category} onChange={e => setFormData({...formData, category: e.target.value})} />
          </div>
          <div className="modal-form-group">
            <label className="modal-form-label">Date</label>
            <input type="date" required className="modal-input" value={formData.date} onChange={e => setFormData({...formData, date: e.target.value})} />
          </div>
          <div className="modal-form-group">
            <label className="modal-form-label">Description (Optional)</label>
            <input type="text" className="modal-input" value={formData.description} onChange={e => setFormData({...formData, description: e.target.value})} />
          </div>
          <div className="modal-actions">
            <button type="button" className="modal-btn modal-btn-cancel" onClick={() => setIsModalOpen(false)}>Cancel</button>
            <button type="submit" className="modal-btn modal-btn-submit">Save Transaction</button>
          </div>
        </form>
      </Modal>
    </>
  );
}
