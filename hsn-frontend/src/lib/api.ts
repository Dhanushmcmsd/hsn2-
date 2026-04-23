const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";

function getAvailableStorages(): Storage[] {
  if (typeof window === "undefined") return [];
  return [localStorage, sessionStorage];
}

function getToken(key: string): string | null {
  for (const storage of getAvailableStorages()) {
    const value = storage.getItem(key);
    if (value) return value;
  }
  return null;
}

function getTokenStorage(key: string): Storage | null {
  for (const storage of getAvailableStorages()) {
    if (storage.getItem(key)) return storage;
  }
  return null;
}

export interface HSNMatch {
  hsn_code: string;
  description: string;
  full_description?: string;
  score: number;
  method: string;
  gst_rate?: number;
  chapter?: string;
  heading?: string;
}
export interface HSNCodeRow {
  hsn_code: string;
  description: string;
  full_description: string;
  gst_rate: number;
  category?: string | null;
  chapter?: string | null;
  heading?: string | null;
  section?: string | null;
}
export interface PredictResponse {
  request_id: string; input_text: string; top_match: HSNMatch;
  alternatives: HSNMatch[]; confidence: number; confidence_label: "high" | "medium" | "low";
  needs_review: boolean; processing_time_ms: number;
}
export interface UserOut { id: number; email: string; full_name?: string; is_active: boolean; }
export interface TokenResponse { access_token: string; refresh_token: string; token_type: string; }
export interface AuthTokenResponse extends TokenResponse { expires_in?: number; }

type Opts = RequestInit & { skipAuth?: boolean };

export const authStorage = {
  getAccessToken: () => getToken(ACCESS_TOKEN_KEY),
  getRefreshToken: () => getToken(REFRESH_TOKEN_KEY),
  setTokens(accessToken: string, refreshToken: string, remember = true) {
    if (typeof window === "undefined") return;
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    sessionStorage.removeItem(REFRESH_TOKEN_KEY);

    const storage = remember ? localStorage : sessionStorage;
    storage.setItem(ACCESS_TOKEN_KEY, accessToken);
    storage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  },
  updateTokens(accessToken: string, refreshToken: string) {
    if (typeof window === "undefined") return;
    const storage =
      getTokenStorage(REFRESH_TOKEN_KEY) ??
      getTokenStorage(ACCESS_TOKEN_KEY) ??
      localStorage;
    storage.setItem(ACCESS_TOKEN_KEY, accessToken);
    storage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  },
  clearTokens() {
    if (typeof window === "undefined") return;
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  },
};

async function request<T>(path: string, opts: Opts = {}): Promise<T> {
  const { skipAuth, ...init } = opts;
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as Record<string, string>) };
  if (!skipAuth && typeof window !== "undefined") {
    const token = authStorage.getAccessToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  let res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  if (res.status === 401 && !skipAuth && typeof window !== "undefined") {
    const refresh = authStorage.getRefreshToken();
    if (refresh) {
      const rr = await fetch(`${BASE_URL}/auth/refresh`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (rr.ok) {
        const data = await rr.json();
        authStorage.updateTokens(data.access_token, data.refresh_token);
        headers["Authorization"] = `Bearer ${data.access_token}`;
        res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
      } else { authStorage.clearTokens(); window.location.href = "/login"; }
    }
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export const authApi = {
  register: (email: string, password: string, full_name?: string) =>
    request<UserOut>("/auth/register", { method: "POST", body: JSON.stringify({ email, password, full_name }), skipAuth: true }),
  login: (email: string, password: string) => {
    const form = new URLSearchParams({ username: email, password });
    return request<AuthTokenResponse>("/auth/login", {
      method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(), skipAuth: true,
    });
  },
  me: () => request<UserOut>("/auth/me"),
};

export const hsnApi = {
  predict: (text: string) => request<PredictResponse>("/predict", { method: "POST", body: JSON.stringify({ text }) }),
  getByCode: (code: string) => request<HSNCodeRow>(`/hsn/${encodeURIComponent(code)}`),
  expandAbbreviations: (text: string) => request<{ original: string; expanded: string; changed: boolean }>("/expand-abbreviations", { method: "POST", body: JSON.stringify({ text }) }),
  health: () => request<{ status: string }>("/health"),
  reviewPending: () => request<unknown[]>("/review/pending"),
};
