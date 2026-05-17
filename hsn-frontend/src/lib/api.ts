/** Backend origin for API calls. See README_DEPLOYMENT.md (Vercel + Render). */
function getApiBaseUrl(): string {
  const explicit =
    process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/$/, "") ||
    process.env.NEXT_PUBLIC_BACKEND_URL?.trim().replace(/\/$/, "");
  if (explicit) return explicit;
  if (process.env.NODE_ENV === "development") return "http://localhost:8000";
  // Production: same-origin proxy via next.config rewrites (/api → BACKEND_URL)
  return "/api";
}

const BASE_URL = getApiBaseUrl();
const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";
const REMEMBER_ME_KEY = "remember_me";

/** Per-request timeouts (ms) */
const LOGIN_TIMEOUT_MS = 90_000;
const AUTH_ME_TIMEOUT_MS = 45_000;
const PREDICT_TIMEOUT_MS = 60_000;
const BATCH_TIMEOUT_BASE_MS = 15_000;
const BATCH_TIMEOUT_PER_QUERY_MS = 1_200;
const BATCH_TIMEOUT_MAX_MS = 180_000;
const HEALTH_TIMEOUT_MS = 25_000;

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
export interface BatchResultRow {
  query: string;
  hsn_code?: string | null;
  description?: string | null;
  gst_rate?: number | null;
  confidence: number;
  confidence_label: string;
  match_method: string;
  alternatives: HSNMatch[];
  error?: string | null;
}
export interface BatchResponse {
  results: BatchResultRow[];
  total: number;
  matched: number;
  unmatched: number;
}
export interface UserOut { id: number; email: string; full_name?: string; is_active: boolean; }
export interface TokenResponse { access_token: string; refresh_token: string; token_type: string; }
export interface AuthTokenResponse extends TokenResponse { expires_in?: number; }

type Opts = RequestInit & { skipAuth?: boolean; timeout?: number };

function batchTimeoutMs(queryCount: number): number {
  return Math.min(
    BATCH_TIMEOUT_MAX_MS,
    BATCH_TIMEOUT_BASE_MS + queryCount * BATCH_TIMEOUT_PER_QUERY_MS,
  );
}

function formatFetchError(error: unknown, timeoutMs: number): Error {
  if (error instanceof Error && error.name === "AbortError") {
    return new Error(
      `Request timed out after ${Math.round(timeoutMs / 1000)}s. ` +
        "The server may be waking up (Render free tier) — wait a moment and try again, " +
        "or use a smaller Excel batch."
    );
  }
  if (error instanceof TypeError) {
    return new Error(
      "Cannot reach the API server. On Vercel, set BACKEND_URL or NEXT_PUBLIC_API_URL to your Render URL, then redeploy."
    );
  }
  return error instanceof Error ? error : new Error("Network request failed");
}

export const authStorage = {
  getAccessToken: () => getToken(ACCESS_TOKEN_KEY),
  getRefreshToken: () => getToken(REFRESH_TOKEN_KEY),
  getRememberPreference: () => {
    if (typeof window === "undefined") return true;
    const value = localStorage.getItem(REMEMBER_ME_KEY);
    if (value == null) return true;
    return value === "true";
  },
  setTokens(accessToken: string, refreshToken: string, remember = true) {
    if (typeof window === "undefined") return;
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    sessionStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.setItem(REMEMBER_ME_KEY, String(remember));

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
  setRememberPreference(remember: boolean) {
    if (typeof window === "undefined") return;
    localStorage.setItem(REMEMBER_ME_KEY, String(remember));
  },
};

async function fetchWithTimeout(url: string, options: RequestInit, timeout: number): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    throw formatFetchError(error, timeout);
  }
}

async function request<T>(path: string, opts: Opts = {}): Promise<T> {
  const { skipAuth, timeout = PREDICT_TIMEOUT_MS, ...init } = opts;
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as Record<string, string>) };
  if (!skipAuth && typeof window !== "undefined") {
    const token = authStorage.getAccessToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  let res = await fetchWithTimeout(`${BASE_URL}${path}`, { ...init, headers }, timeout);
  if (res.status === 401 && !skipAuth && typeof window !== "undefined") {
    const refresh = authStorage.getRefreshToken();
    if (refresh) {
      const rr = await fetchWithTimeout(`${BASE_URL}/auth/refresh`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      }, timeout);
      if (rr.ok) {
        const data = await rr.json();
        authStorage.updateTokens(data.access_token, data.refresh_token);
        headers["Authorization"] = `Bearer ${data.access_token}`;
        res = await fetchWithTimeout(`${BASE_URL}${path}`, { ...init, headers }, timeout);
      } else { authStorage.clearTokens(); window.location.href = "/login"; }
    }
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    const detail = (err as { detail?: unknown }).detail;
    throw new Error(
      typeof detail === "string" ? detail : `HTTP ${res.status}`
    );
  }
  return res.json();
}

/** Wake Render / verify API is reachable (call before login or bulk). */
export async function warmupBackend(): Promise<boolean> {
  try {
    const res = await fetchWithTimeout(
      `${BASE_URL}/health`,
      { method: "GET", cache: "no-store" },
      HEALTH_TIMEOUT_MS,
    );
    return res.ok;
  } catch {
    return false;
  }
}

export const authApi = {
  register: (email: string, password: string, full_name?: string) =>
    request<UserOut>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name }),
      skipAuth: true,
      timeout: LOGIN_TIMEOUT_MS,
    }),
  login: async (email: string, password: string) => {
    await warmupBackend();
    const form = new URLSearchParams({ username: email, password });
    return request<AuthTokenResponse>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
      skipAuth: true,
      timeout: LOGIN_TIMEOUT_MS,
    });
  },
  me: (opts?: { timeout?: number }) =>
    request<UserOut>("/auth/me", { timeout: opts?.timeout ?? AUTH_ME_TIMEOUT_MS }),
};

export const hsnApi = {
  predict: async (text: string, opts?: { timeout?: number }): Promise<PredictResponse> => {
    const timeout = opts?.timeout ?? PREDICT_TIMEOUT_MS;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (typeof window !== "undefined") {
      const token = authStorage.getAccessToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
    }
    let res = await fetchWithTimeout(
      `${BASE_URL}/predict`,
      { method: "POST", headers, body: JSON.stringify({ text }) },
      timeout
    );
    if (res.status === 401 && typeof window !== "undefined") {
      const refresh = authStorage.getRefreshToken();
      if (refresh) {
        const rr = await fetchWithTimeout(
          `${BASE_URL}/auth/refresh`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refresh }),
          },
          timeout
        );
        if (rr.ok) {
          const data = (await rr.json()) as TokenResponse;
          authStorage.updateTokens(data.access_token, data.refresh_token);
          headers["Authorization"] = `Bearer ${data.access_token}`;
          res = await fetchWithTimeout(
            `${BASE_URL}/predict`,
            { method: "POST", headers, body: JSON.stringify({ text }) },
            timeout
          );
        } else {
          authStorage.clearTokens();
          window.location.href = "/login";
          throw new Error("Authentication required");
        }
      }
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      const detail = (err as { detail?: unknown }).detail;
      throw new Error(
        typeof detail === "string" ? detail : `HTTP ${res.status}`
      );
    }
    return (await res.json()) as PredictResponse;
  },
  batch: async (queries: string[], opts?: { timeout?: number }) => {
    const timeout = opts?.timeout ?? batchTimeoutMs(queries.length);
    return request<BatchResponse>("/hsn/batch", {
      method: "POST",
      body: JSON.stringify({ queries }),
      timeout,
    });
  },
  getByCode: (code: string) => request<HSNCodeRow>(`/hsn/${encodeURIComponent(code)}`),
  expandAbbreviations: (text: string) => request<{ original: string; expanded: string; changed: boolean }>("/expand-abbreviations", { method: "POST", body: JSON.stringify({ text }) }),
  health: () => request<{ status: string }>("/health", { timeout: HEALTH_TIMEOUT_MS, skipAuth: true }),
  reviewPending: () => request<unknown[]>("/review/pending"),
};
