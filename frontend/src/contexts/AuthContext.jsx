import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { ApiError, apiRequest } from "../lib/api";
import { clearCachedResources } from "../lib/resourceCache";

const AuthContext = createContext(null);
const SESSION_STORAGE_KEY = "moneyhub.auth.user";

function readStoredUser() {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
    return null;
  }
}

function persistStoredUser(user) {
  if (typeof window === "undefined") {
    return;
  }
  if (!user) {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
    return;
  }
  window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(user));
}

function sessionUserFromPayload(payload) {
  return {
    id: payload.id,
    username: payload.username,
    email: payload.email,
    profile: payload.profile
  };
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const requestVersionRef = useRef(0);

  const refreshSession = useCallback(async (options) => {
    const requestVersion = ++requestVersionRef.current;
    const isBackgroundRefresh = Boolean(options?.background);

    if (!isBackgroundRefresh) {
      setLoading(true);
    }

    try {
      const nextUser = await apiRequest("/api/auth/me");
      if (requestVersion !== requestVersionRef.current) {
        return;
      }
      setUser((currentUser) => {
        if (currentUser?.id && currentUser.id !== nextUser.id) {
          clearCachedResources();
        }
        return nextUser;
      });
      persistStoredUser(nextUser);
    } catch (error) {
      if (requestVersion !== requestVersionRef.current) {
        return;
      }

      if (isBackgroundRefresh && !(error instanceof ApiError && error.status === 401)) {
        return;
      }

      if (error instanceof ApiError && error.status === 401) {
        await apiRequest("/api/auth/logout", { method: "POST" }).catch(() => {});
      }

      clearCachedResources();
      setUser(null);
      persistStoredUser(null);
    } finally {
      if (requestVersion === requestVersionRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const storedUser = readStoredUser();
    if (storedUser) {
      setUser(storedUser);
      setLoading(false);
    }
    void refreshSession({ background: Boolean(storedUser) });
  }, [refreshSession]);

  async function login(input) {
    const payload = await apiRequest("/api/auth/login", {
      method: "POST",
      body: input
    });
    requestVersionRef.current += 1;
    const nextUser = sessionUserFromPayload(payload);
    clearCachedResources();
    setUser(nextUser);
    persistStoredUser(nextUser);
    setLoading(false);
  }

  async function register(input) {
    await apiRequest("/api/auth/register", {
      method: "POST",
      body: input
    });
    await login({ username: input.username, password: input.password, remember: true });
  }

  async function logout() {
    requestVersionRef.current += 1;
    await apiRequest("/api/auth/logout", {
      method: "POST"
    });
    clearCachedResources();
    setUser(null);
    persistStoredUser(null);
    setLoading(false);
  }

  async function updateProfile(input) {
    const payload = await apiRequest("/api/auth/profile", {
      method: "PUT",
      body: input
    });
    requestVersionRef.current += 1;
    const nextUser = sessionUserFromPayload(payload);
    setUser(nextUser);
    persistStoredUser(nextUser);
    return nextUser;
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        refreshSession,
        login,
        register,
        logout,
        updateProfile
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
