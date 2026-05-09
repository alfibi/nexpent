const SETTINGS_STORAGE_KEY = "moneyhub.app.settings";

export const defaultAppSettings = {
  defaultCurrency: "USD",
  defaultCountry: "US",
  themeMode: "dark"
};

function normalizeSettings(settings) {
  return {
    ...defaultAppSettings,
    ...settings,
    defaultCurrency: String(settings.defaultCurrency || defaultAppSettings.defaultCurrency).toUpperCase(),
    defaultCountry: String(settings.defaultCountry || defaultAppSettings.defaultCountry).toUpperCase(),
    themeMode: settings.themeMode === "light" ? "light" : "dark"
  };
}

export function applyAppSettings(settings = getAppSettings()) {
  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = settings.themeMode;
  }
}

export function getAppSettings() {
  if (typeof window === "undefined") {
    return defaultAppSettings;
  }

  const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
  if (!raw) {
    return defaultAppSettings;
  }

  try {
    return normalizeSettings(JSON.parse(raw));
  } catch {
    window.localStorage.removeItem(SETTINGS_STORAGE_KEY);
    return defaultAppSettings;
  }
}

export function saveAppSettings(settings) {
  const nextSettings = normalizeSettings(settings);

  if (typeof window !== "undefined") {
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(nextSettings));
  }

  applyAppSettings(nextSettings);
  return nextSettings;
}
