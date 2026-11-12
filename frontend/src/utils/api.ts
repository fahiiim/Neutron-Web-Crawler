const API_OVERRIDE_KEY = "neutron_api_base_url";

function cleanBaseUrl(raw: string | undefined | null): string {
  return (raw || "").trim().replace(/\/+$/, "");
}

export function getApiBaseUrl(): string {
  try {
    const saved = cleanBaseUrl(localStorage.getItem(API_OVERRIDE_KEY));
    if (saved) return saved;
  } catch {
    // Ignore storage access restrictions
  }
  return cleanBaseUrl(import.meta.env.VITE_API_BASE_URL as string | undefined);
}

export function setApiBaseUrl(url: string): void {
  const cleaned = cleanBaseUrl(url);
  try {
    if (!cleaned) {
      localStorage.removeItem(API_OVERRIDE_KEY);
    } else {
      localStorage.setItem(API_OVERRIDE_KEY, cleaned);
    }
  } catch {
    // Ignore storage errors
  }
}

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const base = getApiBaseUrl();
  return base ? `${base}${normalizedPath}` : normalizedPath;
}

