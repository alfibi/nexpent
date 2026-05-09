import { useEffect, useState } from "react";
import { LogOut, Moon, Save, Settings, ShieldCheck, Sun, Trash2, UserRound } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { apiRequest } from "../lib/api";
import { getAppSettings, saveAppSettings } from "../lib/settings";
import { useAuth } from "../contexts/AuthContext.jsx";

const emptyProfile = {
  full_name: "",
  dob: "",
  phone: "",
  address_line1: "",
  address_line2: "",
  city: "",
  state: "",
  country: "",
  postal_code: ""
};

function formFromUser(user) {
  return {
    ...emptyProfile,
    ...(user?.profile || {})
  };
}

function normalizeProfilePayload(formData) {
  return Object.fromEntries(
    Object.entries(formData).map(([key, value]) => {
      const nextValue = typeof value === "string" ? value.trim() : value;
      return [key, nextValue || null];
    })
  );
}

export default function Profile() {
  const navigate = useNavigate();
  const { user, logout, updateProfile } = useAuth();
  const [activePanel, setActivePanel] = useState("profile");
  const [formData, setFormData] = useState(() => formFromUser(user));
  const [settingsData, setSettingsData] = useState(() => getAppSettings());
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setFormData(formFromUser(user));
  }, [user]);

  function updateField(field, value) {
    setFormData((current) => ({ ...current, [field]: value }));
    setStatus("");
    setError("");
  }

  function updateSetting(field, value) {
    setSettingsData((current) => ({ ...current, [field]: value }));
    setStatus("");
    setError("");
  }

  function handleThemeChange(themeMode) {
    const nextSettings = saveAppSettings({ ...settingsData, themeMode });
    setSettingsData(nextSettings);
    setStatus("Theme updated");
    setError("");
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSaving(true);
    setStatus("");
    setError("");

    try {
      await updateProfile(normalizeProfilePayload(formData));
      setStatus("Profile saved");
    } catch (err) {
      setError(err.message || "Could not save profile");
    } finally {
      setSaving(false);
    }
  }

  function handleSettingsSubmit(event) {
    event.preventDefault();
    setSettingsData(saveAppSettings(settingsData));
    setStatus("Settings saved");
    setError("");
  }

  async function handleDeleteFinancialData() {
    if (!confirm("Delete your connected financial data, transactions, budgets, goals, receipts, and insights?")) {
      return;
    }

    try {
      await apiRequest("/api/auth/me/data", { method: "DELETE" });
      setStatus("Financial data deleted");
      setError("");
    } catch (err) {
      setError(err.message || "Could not delete financial data");
    }
  }

  async function handleDeactivateAccount() {
    if (!confirm("Deactivate this account and sign out?")) {
      return;
    }

    try {
      await apiRequest("/api/auth/me", { method: "DELETE" });
      await logout().catch(() => {});
      navigate("/auth", { replace: true });
    } catch (err) {
      setError(err.message || "Could not deactivate account");
    }
  }

  async function handleLogout() {
    await logout();
    navigate("/auth", { replace: true });
  }

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">Profile</div>
          <div className="profile-subtitle">{user?.email}</div>
        </div>
        <div className="avatar profile-avatar">
          {(user?.username || "U").substring(0, 2).toUpperCase()}
        </div>
      </div>

      <div className="profile-grid">
        <section className="profile-panel">
          <div className="nav-tabs profile-tabs">
            <button type="button" className={`nav-tab ${activePanel === "profile" ? "active" : ""}`} onClick={() => setActivePanel("profile")}>Profile</button>
            <button type="button" className={`nav-tab ${activePanel === "settings" ? "active" : ""}`} onClick={() => setActivePanel("settings")}>Settings</button>
          </div>

          {activePanel === "profile" ? (
            <>
              <div className="section-header">
                <span className="section-title">Personal Details</span>
                <span className="badge">Account</span>
              </div>

              <form onSubmit={handleSubmit}>
                <div className="profile-form-grid">
                  <div className="modal-form-group">
                    <label className="modal-form-label">Full Name</label>
                    <input className="modal-input" value={formData.full_name || ""} onChange={(event) => updateField("full_name", event.target.value)} />
                  </div>
                  <div className="modal-form-group">
                    <label className="modal-form-label">Date Of Birth</label>
                    <input type="date" className="modal-input" value={formData.dob || ""} onChange={(event) => updateField("dob", event.target.value)} />
                  </div>
                  <div className="modal-form-group">
                    <label className="modal-form-label">Phone</label>
                    <input className="modal-input" value={formData.phone || ""} onChange={(event) => updateField("phone", event.target.value)} />
                  </div>
                  <div className="modal-form-group">
                    <label className="modal-form-label">Country</label>
                    <input className="modal-input" value={formData.country || ""} onChange={(event) => updateField("country", event.target.value)} />
                  </div>
                  <div className="modal-form-group profile-wide">
                    <label className="modal-form-label">Address Line 1</label>
                    <input className="modal-input" value={formData.address_line1 || ""} onChange={(event) => updateField("address_line1", event.target.value)} />
                  </div>
                  <div className="modal-form-group profile-wide">
                    <label className="modal-form-label">Address Line 2</label>
                    <input className="modal-input" value={formData.address_line2 || ""} onChange={(event) => updateField("address_line2", event.target.value)} />
                  </div>
                  <div className="modal-form-group">
                    <label className="modal-form-label">City</label>
                    <input className="modal-input" value={formData.city || ""} onChange={(event) => updateField("city", event.target.value)} />
                  </div>
                  <div className="modal-form-group">
                    <label className="modal-form-label">State</label>
                    <input className="modal-input" value={formData.state || ""} onChange={(event) => updateField("state", event.target.value)} />
                  </div>
                  <div className="modal-form-group">
                    <label className="modal-form-label">Postal Code</label>
                    <input className="modal-input" value={formData.postal_code || ""} onChange={(event) => updateField("postal_code", event.target.value)} />
                  </div>
                </div>

                {(status || error) && (
                  <div className={`profile-message ${error ? "profile-message-error" : ""}`}>
                    {error || status}
                  </div>
                )}

                <div className="modal-actions profile-actions">
                  <button type="submit" className="modal-btn modal-btn-submit" disabled={saving}>
                    <Save size={15} /> {saving ? "Saving..." : "Save Profile"}
                  </button>
                </div>
              </form>
            </>
          ) : (
            <>
              <div className="section-header">
                <span className="section-title">Settings</span>
                <span className="badge">Account</span>
              </div>

              <form onSubmit={handleSettingsSubmit}>
                <div className="settings-section">
                  <div className="settings-section-title">Appearance</div>
                  <div className="theme-toggle">
                    <button type="button" className={`theme-option ${settingsData.themeMode === "dark" ? "active" : ""}`} onClick={() => handleThemeChange("dark")}>
                      <Moon size={16} /> Dark
                    </button>
                    <button type="button" className={`theme-option ${settingsData.themeMode === "light" ? "active" : ""}`} onClick={() => handleThemeChange("light")}>
                      <Sun size={16} /> Light
                    </button>
                  </div>
                </div>

                <div className="settings-section">
                  <div className="settings-section-title">Financial Defaults</div>
                  <div className="profile-form-grid">
                    <div className="modal-form-group">
                      <label className="modal-form-label">Default Currency</label>
                      <select className="modal-select" value={settingsData.defaultCurrency} onChange={(event) => updateSetting("defaultCurrency", event.target.value)}>
                        <option value="USD">USD</option>
                        <option value="EUR">EUR</option>
                        <option value="GBP">GBP</option>
                        <option value="INR">INR</option>
                        <option value="CAD">CAD</option>
                        <option value="AUD">AUD</option>
                      </select>
                    </div>
                    <div className="modal-form-group">
                      <label className="modal-form-label">Default Country</label>
                      <select className="modal-select" value={settingsData.defaultCountry} onChange={(event) => updateSetting("defaultCountry", event.target.value)}>
                        <option value="US">United States</option>
                        <option value="GB">United Kingdom</option>
                        <option value="IN">India</option>
                        <option value="CA">Canada</option>
                        <option value="AU">Australia</option>
                      </select>
                    </div>
                  </div>
                </div>

                {(status || error) && (
                  <div className={`profile-message ${error ? "profile-message-error" : ""}`}>
                    {error || status}
                  </div>
                )}

                <div className="modal-actions profile-actions">
                  <button type="submit" className="modal-btn modal-btn-submit">
                    <Save size={15} /> Save Settings
                  </button>
                </div>
              </form>

              <div className="settings-section settings-account-actions">
                <div className="settings-section-title">Account Actions</div>
                <button type="button" className="btn-outline profile-command" onClick={handleLogout}>
                  <LogOut size={16} /> Log Out
                </button>
                <button type="button" className="btn-outline profile-command profile-danger" onClick={handleDeleteFinancialData}>
                  <Trash2 size={16} /> Delete Financial Data
                </button>
                <button type="button" className="btn-outline profile-command profile-danger" onClick={handleDeactivateAccount}>
                  <Trash2 size={16} /> Deactivate Account
                </button>
              </div>
            </>
          )}
        </section>

        <aside className="profile-panel profile-account-panel">
          <div className="profile-card-header">
            <div className="tx-icon">
              <UserRound size={18} />
            </div>
            <div>
              <div className="tx-name">{user?.profile?.full_name || user?.username}</div>
              <div className="tx-meta">{user?.email}</div>
            </div>
          </div>

          <div className="profile-security-note">
            <ShieldCheck size={17} />
            <span>Bank credentials stay out of MoneyHub. Connected provider tokens remain server-side.</span>
          </div>

          <button type="button" className="btn-outline profile-command" onClick={() => setActivePanel("settings")}>
            <Settings size={16} /> Settings
          </button>
        </aside>
      </div>
    </>
  );
}
