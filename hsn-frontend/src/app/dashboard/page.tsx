"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { hsnApi, authApi, type PredictResponse, type UserOut } from "@/lib/api";

const CONFIDENCE_COLOR: Record<string, string> = {
  high: "bg-green-100 text-green-700 border-green-200",
  medium: "bg-yellow-100 text-yellow-700 border-yellow-200",
  low: "bg-red-100 text-red-700 border-red-200",
};

export default function Dashboard() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [user, setUser] = useState<UserOut | null>(null);

  useEffect(() => {
    if (!localStorage.getItem("access_token")) { router.replace("/login"); return; }
    authApi.me().then(setUser).catch(() => router.replace("/login"));
  }, []);

  async function handlePredict(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setError(""); setLoading(true); setResult(null);
    try {
      setResult(await hsnApi.predict(query));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Prediction failed");
    } finally { setLoading(false); }
  }

  function signOut() { localStorage.clear(); router.push("/login"); }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-100 px-8 py-4">
        <div className="max-w-4xl mx-auto flex justify-between items-center">
          <span className="font-semibold text-gray-900">HSN Classifier</span>
          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-500">{user?.email}</span>
            <button onClick={signOut}
              className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 transition">
              Sign out
            </button>
          </div>
        </div>
      </nav>

      <main className="max-w-3xl mx-auto px-8 py-12">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900 mb-1">HSN Code Lookup</h1>
          <p className="text-gray-500 text-sm">Enter any product description to find its GST HSN code instantly</p>
        </div>

        <form onSubmit={handlePredict} className="flex gap-3 mb-8">
          <input value={query} onChange={e => setQuery(e.target.value)}
            placeholder="e.g. laptop computer, cotton shirt, steel pipes, mobile phone..."
            className="flex-1 px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white" />
          <button type="submit" disabled={loading || !query.trim()}
            className="px-6 py-3 bg-gray-900 text-white rounded-xl text-sm font-medium hover:bg-gray-700 disabled:opacity-40 transition whitespace-nowrap">
            {loading ? "Classifying..." : "Classify →"}
          </button>
        </form>

        {error && <div className="mb-6 p-4 bg-red-50 border border-red-100 text-red-600 text-sm rounded-xl">{error}</div>}

        {result && (
          <div className="space-y-4">
            <div className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm">
              <div className="flex justify-between items-start mb-3">
                <div>
                  <div className="text-4xl font-bold text-blue-600 font-mono">{result.top_match.hsn_code}</div>
                  <div className="text-gray-600 mt-1">{result.top_match.description}</div>
                </div>
                <span className={`text-xs font-medium px-2.5 py-1 rounded-full border ${CONFIDENCE_COLOR[result.confidence_label]}`}>
                  {result.confidence_label} · {Math.round(result.confidence * 100)}%
                </span>
              </div>
              <div className="flex gap-4 text-xs text-gray-400 mt-4 pt-4 border-t border-gray-50">
                <span>Score: {result.top_match.score.toFixed(3)}</span>
                <span>{result.processing_time_ms.toFixed(0)}ms</span>
                <span>Method: {result.top_match.method}</span>
                {result.needs_review && <span className="text-orange-500">⚠ Flagged for review</span>}
              </div>
            </div>

            {result.alternatives.length > 0 && (
              <div>
                <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2 px-1">Other possible matches</p>
                <div className="space-y-2">
                  {result.alternatives.map((alt) => (
                    <div key={alt.hsn_code} className="flex items-center justify-between bg-white rounded-xl border border-gray-100 px-4 py-3 text-sm">
                      <span className="font-mono font-semibold text-gray-700 w-16">{alt.hsn_code}</span>
                      <span className="text-gray-500 flex-1 mx-4 truncate">{alt.description}</span>
                      <span className="text-gray-400 text-xs">{(alt.score * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {!result && !loading && (
          <div className="text-center py-16 text-gray-400">
            <div className="text-5xl mb-4">🔍</div>
            <p className="text-sm">Enter a product description above to get started</p>
          </div>
        )}
      </main>
    </div>
  );
}
