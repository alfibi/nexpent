import { apiRequest } from "./api";

const STORAGE_PREFIX = "moneyhub.resource.";
const inFlightRequests = new Map();
const resourceVersions = new Map();

const resources = {
  dashboardOverview: { path: "/api/dashboard/overview", ttl: 45_000 },
  transactions: { path: "/api/transactions", ttl: 30_000 },
  receipts: { path: "/api/receipts", ttl: 30_000 },
  accounts: { path: "/api/banks/accounts", ttl: 45_000 },
  goals: { path: "/api/goals", ttl: 45_000 },
  financialToolsOverview: { path: "/api/financial-tools/overview", ttl: 45_000 },
  config: { path: "/config", ttl: 300_000 },
  aiInsights: { path: "/api/ai/insights", ttl: 60_000 },
  analyticsInsights: { path: "/insights", ttl: 60_000 }
};

function storageKey(resourceKey) {
  return `${STORAGE_PREFIX}${resourceKey}`;
}

function bumpResourceVersion(resourceKey) {
  resourceVersions.set(resourceKey, (resourceVersions.get(resourceKey) || 0) + 1);
}

function readEntry(resourceKey) {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.sessionStorage.getItem(storageKey(resourceKey));
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw);
  } catch {
    window.sessionStorage.removeItem(storageKey(resourceKey));
    return null;
  }
}

function writeEntry(resourceKey, data) {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.setItem(
    storageKey(resourceKey),
    JSON.stringify({ data, cachedAt: Date.now() })
  );
}

export function readCachedResource(resourceKey) {
  return readEntry(resourceKey)?.data ?? null;
}

export function invalidateCachedResource(resourceKey) {
  if (typeof window !== "undefined") {
    window.sessionStorage.removeItem(storageKey(resourceKey));
  }
  bumpResourceVersion(resourceKey);
  inFlightRequests.delete(resourceKey);
}

export function clearCachedResources() {
  if (typeof window === "undefined") {
    return;
  }

  Object.keys(window.sessionStorage)
    .filter((key) => key.startsWith(STORAGE_PREFIX))
    .forEach((key) => window.sessionStorage.removeItem(key));
  inFlightRequests.clear();
}

export function invalidateFinancialResources() {
  [
    "dashboardOverview",
    "transactions",
    "receipts",
    "accounts",
    "goals",
    "financialToolsOverview",
    "aiInsights",
    "analyticsInsights"
  ].forEach(invalidateCachedResource);
}

export async function loadCachedResource(resourceKey, options = {}) {
  const resource = resources[resourceKey];
  if (!resource) {
    throw new Error(`Unknown cached resource: ${resourceKey}`);
  }

  const ttl = options.ttl ?? resource.ttl;
  const cached = readEntry(resourceKey);
  if (!options.force && cached && Date.now() - cached.cachedAt <= ttl) {
    return cached.data;
  }

  if (!options.force && inFlightRequests.has(resourceKey)) {
    return inFlightRequests.get(resourceKey);
  }

  if (options.force) {
    bumpResourceVersion(resourceKey);
  }
  const requestVersion = resourceVersions.get(resourceKey) || 0;
  const request = apiRequest(resource.path)
    .then((data) => {
      if ((resourceVersions.get(resourceKey) || 0) === requestVersion) {
        writeEntry(resourceKey, data);
      }
      return data;
    })
    .finally(() => {
      if (inFlightRequests.get(resourceKey) === request) {
        inFlightRequests.delete(resourceKey);
      }
    });

  inFlightRequests.set(resourceKey, request);
  return request;
}

export function prefetchAppData() {
  const run = () => {
    void Promise.allSettled([
      loadCachedResource("dashboardOverview"),
      loadCachedResource("transactions"),
      loadCachedResource("accounts"),
      loadCachedResource("goals"),
      loadCachedResource("financialToolsOverview"),
      loadCachedResource("aiInsights"),
      loadCachedResource("config")
    ]);
  };

  if (typeof window !== "undefined" && "requestIdleCallback" in window) {
    const idleId = window.requestIdleCallback(run, { timeout: 1200 });
    return () => window.cancelIdleCallback?.(idleId);
  }

  const timeoutId = window.setTimeout(run, 250);
  return () => window.clearTimeout(timeoutId);
}
