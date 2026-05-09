import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { buildNexpentNotifications } from "../lib/notificationRules";
import { loadCachedResource, readCachedResource } from "../lib/resourceCache";

const NotificationContext = createContext(null);
const READ_STORAGE_KEY = "nexpent.notifications.read";
const PUSHED_STORAGE_KEY = "nexpent.notifications.pushed";

function readStoredSet(key) {
  if (typeof window === "undefined") {
    return new Set();
  }

  try {
    return new Set(JSON.parse(window.localStorage.getItem(key) || "[]"));
  } catch {
    window.localStorage.removeItem(key);
    return new Set();
  }
}

function writeStoredSet(key, value) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(key, JSON.stringify([...value]));
}

function browserNotificationPermission() {
  if (typeof window === "undefined" || !("Notification" in window)) {
    return "unsupported";
  }
  return window.Notification.permission;
}

export function NotificationProvider({ children }) {
  const [notifications, setNotifications] = useState([]);
  const [readIds, setReadIds] = useState(() => readStoredSet(READ_STORAGE_KEY));
  const [permission, setPermission] = useState(() => browserNotificationPermission());

  const refreshNotifications = useCallback(async (options = {}) => {
    try {
      const [overview, transactions, aiInsights, financialTools] = await Promise.all([
        loadCachedResource("dashboardOverview", options),
        loadCachedResource("transactions", options),
        loadCachedResource("aiInsights").catch(() => readCachedResource("aiInsights") || { insights: [] }),
        loadCachedResource("financialToolsOverview", options).catch(() => readCachedResource("financialToolsOverview") || null)
      ]);

      const nextNotifications = buildNexpentNotifications({
        overview,
        transactions: transactions?.transactions || [],
        aiInsights: aiInsights?.insights || [],
        financialTools
      });
      setNotifications(nextNotifications);
      return nextNotifications;
    } catch (err) {
      console.error("Failed to refresh notifications", err);
      return [];
    }
  }, []);

  useEffect(() => {
    void refreshNotifications();
  }, [refreshNotifications]);

  useEffect(() => {
    if (permission !== "granted" || typeof window === "undefined" || !("Notification" in window)) {
      return;
    }

    const pushedIds = readStoredSet(PUSHED_STORAGE_KEY);
    const urgentNotifications = notifications.filter((item) =>
      ["critical", "high"].includes(item.severity) && !pushedIds.has(item.id)
    );

    for (const item of urgentNotifications.slice(0, 3)) {
      pushedIds.add(item.id);
      new window.Notification(`Nexpent: ${item.title}`, {
        body: item.message,
        tag: item.id
      });
    }
    writeStoredSet(PUSHED_STORAGE_KEY, pushedIds);
  }, [notifications, permission]);

  const requestPermission = useCallback(async () => {
    if (typeof window === "undefined" || !("Notification" in window)) {
      setPermission("unsupported");
      return "unsupported";
    }
    const nextPermission = await window.Notification.requestPermission();
    setPermission(nextPermission);
    return nextPermission;
  }, []);

  const markAllRead = useCallback(() => {
    setReadIds((current) => {
      const next = new Set(current);
      notifications.forEach((item) => next.add(item.id));
      writeStoredSet(READ_STORAGE_KEY, next);
      return next;
    });
  }, [notifications]);

  const unreadCount = useMemo(
    () => notifications.filter((item) => !readIds.has(item.id)).length,
    [notifications, readIds]
  );

  return (
    <NotificationContext.Provider
      value={{
        notifications,
        unreadCount,
        permission,
        refreshNotifications,
        requestPermission,
        markAllRead
      }}
    >
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error("useNotifications must be used within NotificationProvider");
  }
  return context;
}
