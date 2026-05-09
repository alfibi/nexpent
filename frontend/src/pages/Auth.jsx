import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext.jsx";

export default function Auth() {
  const [isLogin, setIsLogin] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const from = location.state?.from?.pathname || "/";

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      if (isLogin) {
        await login({ username, password, remember: true });
      } else {
        await register({ username, email: `${username}@example.com`, password });
      }
      navigate(from, { replace: true });
    } catch (err) {
      setError(err.message || "Authentication failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-logo">
        <div className="auth-logo-mark" style={{ letterSpacing: "-0.03em" }}>M$</div>
        <div style={{ fontFamily: "'Syne', sans-serif", fontSize: "28px", fontWeight: 800, color: "var(--text)" }}>Nexpent</div>
        <div style={{ fontSize: "14px", color: "var(--text3)", marginTop: "4px" }}>Your financial life, unified.</div>
      </div>
      
      <div className="auth-title">{isLogin ? "Welcome back" : "Create Account"}</div>
      <div className="auth-sub" style={{ marginBottom: "32px" }}>
        {isLogin ? "Sign in to your account" : "Sign up for a new account"}
      </div>
      
      {error && <div style={{ color: "var(--accent-red)", marginBottom: "16px", fontSize: "14px", textAlign: "center" }}>{error}</div>}

      <form onSubmit={handleSubmit}>
        <div className="form-field">
          <div className="form-label">Username</div>
          <input 
            className="form-input" 
            type="text" 
            placeholder="alex" 
            value={username}
            onChange={e => setUsername(e.target.value)}
            required
          />
        </div>
        
        <div className="form-field">
          <div className="form-label">Password</div>
          <input 
            className="form-input" 
            type="password" 
            placeholder="••••••••••" 
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
          />
        </div>
        
        {isLogin && (
          <div style={{ textAlign: "right", marginBottom: "24px", marginTop: "-4px" }}>
            <span style={{ fontSize: "12px", color: "var(--accent)", fontWeight: 600, cursor: "pointer" }}>Forgot password?</span>
          </div>
        )}
        
        <button type="submit" className="btn-primary" disabled={isSubmitting} style={{ marginTop: isLogin ? "0" : "24px" }}>
          {isSubmitting ? "Please wait..." : (isLogin ? "Sign In" : "Sign Up")}
        </button>
      </form>
      
      <div className="divider">
        <div className="div-line"></div>
        <div className="div-text">or continue with</div>
        <div className="div-line"></div>
      </div>
      
      <button className="btn-outline" type="button">
        <svg width="18" height="18" viewBox="0 0 18 18">
          <path fill="#4285F4" d="M16.51 8H8.98v3h4.3c-.18 1-.74 1.48-1.6 2.04v2.01h2.6a7.8 7.8 0 0 0 2.38-5.88c0-.57-.05-.66-.15-1.18z"/>
          <path fill="#34A853" d="M8.98 17c2.16 0 3.97-.72 5.3-1.94l-2.6-2.04a4.8 4.8 0 0 1-7.18-2.54H1.83v2.07A8 8 0 0 0 8.98 17z"/>
          <path fill="#FBBC05" d="M4.5 10.48A4.8 4.8 0 0 1 4.5 7.5V5.44H1.83a8 8 0 0 0 0 7.11l2.67-2.07z"/>
          <path fill="#EA4335" d="M8.98 3.18c1.17 0 2.23.4 3.06 1.2l2.3-2.3A8 8 0 0 0 1.83 5.44L4.5 7.5a4.77 4.77 0 0 1 4.48-4.32z"/>
        </svg>
        Continue with Google
      </button>
      
      <button className="btn-outline" type="button">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="var(--text2)">
          <path d="M12.96 2c.14 1.07-.31 2.1-.89 2.85-.6.77-1.61 1.37-2.6 1.3-.16-1.02.34-2.07.9-2.74C10.98 2.65 12 2.07 12.96 2zm3.04 12.5c-.54.82-1.1 1.62-1.95 1.63-.85.01-1.12-.5-2.1-.5-.98 0-1.29.49-2.1.51-.82.02-1.44-.84-1.98-1.66C6.68 12.7 6.15 10.5 7 9.08a3.1 3.1 0 0 1 2.6-1.58c.82 0 1.56.55 2.1.55.52 0 1.5-.68 2.52-.58.43.02 1.64.17 2.42 1.3-.07.04-1.44.83-1.43 2.5.01 1.97 1.73 2.63 1.79 2.73z"/>
        </svg>
        Continue with Apple
      </button>
      
      <div style={{ textAlign: "center", marginTop: "32px", fontSize: "13px", color: "var(--text3)" }}>
        {isLogin ? "Don't have an account? " : "Already have an account? "} 
        <span 
          style={{ color: "var(--accent)", fontWeight: 600, cursor: "pointer" }}
          onClick={() => setIsLogin(!isLogin)}
        >
          {isLogin ? "Sign up free" : "Sign in"}
        </span>
      </div>
    </div>
  );
}
