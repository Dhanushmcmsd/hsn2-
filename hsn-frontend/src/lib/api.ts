const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface HSNMatch { hsn_code: string; description: string; score: number; method: string; }
export interface PredictResponse {
  request_id: string; input_text: string; top_match: HSNMatch;
  alternatives: HSNMatch[]; confidence: number; confidence_label: "high" | "medium" | "low";
  needs_review: boolean; processing_time_ms: number;
}
export interface UserOut { id: number; email: string; full_name?: string; is_active: boolean; }
export interface TokenResponse { access_token: string; refresh_token: string; token_type: string; }

type Opts = RequestInit & { skipAuth?: boolean };

async function request<T>(path: string, opts: Opts = {}): Promise<T> {
  const { skipAuth, ...init } = opts;
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as Record<string, string>) };
  if (!skipAuth && typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  let res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  if (res.status === 401 && !skipAuth && typeof window !== "undefined") {
    const refresh = localStorage.getItem("refresh_token");
    if (refresh) {
      const rr = await fetch(`${BASE_URL}/auth/refresh`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (rr.ok) {
        const data = await rr.json();
        localStorage.setItem("access_token", data.access_token);
        localStorage.setItem("refresh_token", data.refresh_token);
        headers["Authorization"] = `Bearer ${data.access_token}`;
        res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
      } else { localStorage.clear(); window.location.href = "/login"; }
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
    return request<TokenResponse>("/auth/login", {
      method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(), skipAuth: true,
    });
  },
  me: () => request<UserOut>("/auth/me"),
};

export const hsnApi = {
  predict: (text: string) => request<PredictResponse>("/predict", { method: "POST", body: JSON.stringify({ text }) }),
  expandAbbreviations: (text: string) => request<{ original: string; expanded: string; changed: boolean }>("/expand-abbreviations", { method: "POST", body: JSON.stringify({ text }) }),
  health: () => request<{ status: string }>("/health"),
  reviewPending: () => request<unknown[]>("/review/pending"),
};
