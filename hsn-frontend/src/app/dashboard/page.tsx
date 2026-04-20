"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { hsnApi, authApi, type PredictResponse, type UserOut } from "@/lib/api";
import * as XLSX from "xlsx";

// ── Types ─────────────────────────────────────────────────────────────────────
interface HSNBatchResult {"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { hsnApi, authApi, type PredictResponse, type UserOut } from "@/lib/api";
import * as XLSX from "xlsx";

// ── Types ─────────────────────────────────────────────────────────────────────
interface HSNBatchResult {
  query: string;
  hsn_code?: string;
  description?: string;
  gst_rate?: number;
  confidence: number;
  confidence_label: "high" | "medium" | "low";
  match_method: string;
  alternatives: { hsn_code: string; description: string; gst_rate: number; confidence: number }[];
  error?: string;
}

interface BatchResponse {
  results: HSNBatchResult[];
  total: number;
  matched: number;
  unmatched: number;
}

// ── Constants ─────────────────────────────────────────────────────────────────
const CONFIDENCE_COLOR: Record<string, string> = {
  high:   "bg-emerald-50 text-emerald-700 border-emerald-200",
  medium: "bg-amber-50 text-amber-700 border-amber-200",
  low:    "bg-red-50 text-red-600 border-red-200",
};

const CONFIDENCE_DOT: Record<string, string> = {
  high:   "bg-emerald-500",
  medium: "bg-amber-400",
  low:    "bg-red-400",
};

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const PAGE_SIZE = 20;

// ── HSN zero-padding helper ───────────────────────────────────────────────────
// FIX: "8013220" → "08013220"  (8-digit left-zero-padded string)
// Must be a STRING in Excel, not a number, or leading zeros are stripped.
function padHsn(code: string | undefined): string {
  if (!code) return "";
  const trimmed = code.trim();
  if (/^\d+$/.test(trimmed)) {
    return trimmed.padStart(8, "0");
  }
  return trimmed;
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function Dashboard() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auth
  const [user, setUser] = useState<UserOut | null>(null);

  // Mode: "single" | "bulk"
  const [mode, setMode] = useState<"single" | "bulk">("single");

  // Single mode
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [singleLoading, setSingleLoading] = useState(false);
  const [singleError, setSingleError] = useState("");

  // Bulk mode
  const [fileName, setFileName] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [selectedCol, setSelectedCol] = useState("");
  const [rawRows, setRawRows] = useState<Record<string, unknown>[]>([]);
  const [bulkResults, setBulkResults] = useState<HSNBatchResult[]>([]);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkError, setBulkError] = useState("");
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [page, setPage] = useState(0);
  const [bulkStats, setBulkStats] = useState<{ matched: number; unmatched: number; total: number } | null>(null);

  useEffect(() => {
    if (!localStorage.getItem("access_token")) { router.replace("/login"); return; }
    authApi.me().then(setUser).catch(() => router.replace("/login"));
  }, []);

  // ── Single predict ──────────────────────────────────────────────────────────
  async function handlePredict(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSingleError(""); setSingleLoading(true); setResult(null);
    try {
      setResult(await hsnApi.predict(query));
    } catch (err: unknown) {
      setSingleError(err instanceof Error ? err.message : "Prediction failed");
    } finally { setSingleLoading(false); }
  }

  // ── File upload ─────────────────────────────────────────────────────────────
  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setBulkResults([]);
    setBulkError("");
    setBulkStats(null);
    setPage(0);

    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const data = ev.target?.result;
        const wb = XLSX.read(data, { type: "binary" });
        const ws = wb.Sheets[wb.SheetNames[0]];
        const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: "" });
        if (rows.length === 0) { setBulkError("File is empty or unreadable."); return; }
        const cols = Object.keys(rows[0]);
        setColumns(cols);
        setSelectedCol(cols[0]);
        setRawRows(rows);
      } catch {
        setBulkError("Could not parse file. Please upload a valid .xlsx or .csv.");
      }
    };
    reader.readAsBinaryString(file);
  }

  // ── Batch process ───────────────────────────────────────────────────────────
  const handleBulkProcess = useCallback(async () => {
    if (!selectedCol || rawRows.length === 0) return;
    setBulkLoading(true);
    setBulkError("");
    setBulkResults([]);
    setBulkStats(null);
    setPage(0);

    const descriptions = rawRows.map((r) => String(r[selectedCol] ?? "").trim()).filter(Boolean);
    const CHUNK = 50;
    const allResults: HSNBatchResult[] = [];
    setProgress({ done: 0, total: descriptions.length });

    const token = localStorage.getItem("access_token") ?? "";

    try {
      for (let i = 0; i < descriptions.length; i += CHUNK) {
        const chunk = descriptions.slice(i, i + CHUNK);
        const res = await fetch(`${BASE_URL}/hsn/batch`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ queries: chunk }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: "Unknown error" }));
          throw new Error(err.detail ?? `HTTP ${res.status}`);
        }
        const data: BatchResponse = await res.json();
        allResults.push(...data.results);
        setProgress({ done: Math.min(i + CHUNK, descriptions.length), total: descriptions.length });
        setBulkResults([...allResults]);
      }
      const matched = allResults.filter((r) => r.hsn_code && !r.error).length;
      setBulkStats({ matched, unmatched: allResults.length - matched, total: allResults.length });
    } catch (err: unknown) {
      setBulkError(err instanceof Error ? err.message : "Batch processing failed");
    } finally {
      setBulkLoading(false);
    }
  }, [selectedCol, rawRows]);

  // ── Download results ────────────────────────────────────────────────────────
  function handleDownload() {
    if (bulkResults.length === 0) return;
    const rows = bulkResults.map((r) => ({
      "Product Description": r.query,
      // FIX: force text type in Excel so "08013220" is not stored as number 8013220
      // Using a cell object with type "s" (string) via sheet_add_aoa later,
      // or simplest fix: prefix with a tab char trick is ugly — instead we set
      // the cell format explicitly via XLSX after building the sheet.
      "HSN Code": padHsn(r.hsn_code),
      "Matched Description": r.description ?? "",
      "GST Rate (%)": r.gst_rate ?? "",
      "Confidence": `${Math.round(r.confidence * 100)}%`,
      "Confidence Label": r.confidence_label,
      "Match Method": r.match_method,
      "Alt 1 HSN": padHsn(r.alternatives[0]?.hsn_code),
      "Alt 1 Desc": r.alternatives[0]?.description ?? "",
      "Alt 2 HSN": padHsn(r.alternatives[1]?.hsn_code),
      "Alt 2 Desc": r.alternatives[1]?.description ?? "",
      "Error": r.error ?? "",
    }));

    const ws = XLSX.utils.json_to_sheet(rows);

    // FIX: Force HSN code columns to text format so Excel preserves leading zeros.
    // XLSX cell format "z" = text. We override every data row (skip header row 0).
    const hsnColIndices = [1, 7, 9]; // "HSN Code", "Alt 1 HSN", "Alt 2 HSN"
    const totalRows = rows.length + 1; // +1 for header
    hsnColIndices.forEach((colIdx) => {
      const colLetter = XLSX.utils.encode_col(colIdx);
      for (let rowIdx = 1; rowIdx < totalRows; rowIdx++) {
        const cellRef = `${colLetter}${rowIdx + 1}`;
        if (ws[cellRef]) {
          ws[cellRef].t = "s"; // type: string — prevents Excel auto-converting to number
        }
      }
    });

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "HSN Results");

    // Column widths
    ws["!cols"] = [
      { wch: 40 }, { wch: 12 }, { wch: 40 }, { wch: 14 },
      { wch: 12 }, { wch: 16 }, { wch: 14 },
      { wch: 12 }, { wch: 30 }, { wch: 12 }, { wch: 30 }, { wch: 20 },
    ];
    XLSX.writeFile(wb, `hsn_results_${Date.now()}.xlsx`);
  }

  function signOut() { localStorage.clear(); router.push("/login"); }

  // ── Paginated slice ─────────────────────────────────────────────────────────
  const pageSlice = bulkResults.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages = Math.ceil(bulkResults.length / PAGE_SIZE);

  // ──────────────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Nav */}
      <nav className="bg-white border-b border-gray-100 px-8 py-4">
        <div className="max-w-5xl mx-auto flex justify-between items-center">
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

      <main className="max-w-5xl mx-auto px-8 py-10">
        {/* Header + mode toggle */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 mb-1">HSN Code Lookup</h1>
            <p className="text-gray-500 text-sm">Classify products to their GST HSN codes instantly</p>
          </div>
          <div className="flex items-center bg-gray-100 rounded-xl p-1 gap-1">
            {(["single", "bulk"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-5 py-2 rounded-lg text-sm font-medium transition ${
                  mode === m
                    ? "bg-white text-gray-900 shadow-sm"
                    : "text-gray-500 hover:text-gray-700"
                }`}
              >
                {m === "single" ? "Single" : "Bulk / Excel"}
              </button>
            ))}
          </div>
        </div>

        {/* ── Single mode ── */}
        {mode === "single" && (
          <div>
            <form onSubmit={handlePredict} className="flex gap-3 mb-8">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="e.g. VKC DL3323 BLUE LADIES 06, HARPIC DISINFTNT BTRM CLNR 500ML..."
                className="flex-1 px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              />
              <button
                type="submit"
                disabled={singleLoading || !query.trim()}
                className="px-6 py-3 bg-gray-900 text-white rounded-xl text-sm font-medium hover:bg-gray-700 disabled:opacity-40 transition whitespace-nowrap"
              >
                {singleLoading ? "Classifying…" : "Classify →"}
              </button>
            </form>

            {singleError && (
              <div className="mb-6 p-4 bg-red-50 border border-red-100 text-red-600 text-sm rounded-xl">{singleError}</div>
            )}

            {result && (
              <div className="space-y-4">
                <div className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm">
                  <div className="flex justify-between items-start mb-3">
                    <div>
                      {/* FIX: display zero-padded HSN code */}
                      <div className="text-4xl font-bold text-blue-600 font-mono">
                        {padHsn(result.top_match.hsn_code)}
                      </div>
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
                          {/* FIX: display zero-padded alternatives */}
                          <span className="font-mono font-semibold text-gray-700 w-20">{padHsn(alt.hsn_code)}</span>
                          <span className="text-gray-500 flex-1 mx-4 truncate">{alt.description}</span>
                          <span className="text-gray-400 text-xs">{(alt.score * 100).toFixed(0)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {!result && !singleLoading && (
              <div className="text-center py-16 text-gray-400">
                <div className="text-5xl mb-4">🔍</div>
                <p className="text-sm">Enter a product description above to get started</p>
              </div>
            )}
          </div>
        )}

        {/* ── Bulk mode ── */}
        {mode === "bulk" && (
          <div className="space-y-6">
            {/* Upload card */}
            <div className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm">
              <h2 className="font-semibold text-gray-800 mb-4 text-sm uppercase tracking-wide">Step 1 — Upload file</h2>
              <div
                onClick={() => fileInputRef.current?.click()}
                className="border-2 border-dashed border-gray-200 rounded-xl p-8 text-center cursor-pointer hover:border-blue-300 hover:bg-blue-50/30 transition group"
              >
                <div className="text-3xl mb-3">📁</div>
                <p className="text-sm font-medium text-gray-700 group-hover:text-blue-700 transition">
                  {fileName ? fileName : "Click to upload .xlsx or .csv"}
                </p>
                <p className="text-xs text-gray-400 mt-1">Max 500 rows per batch</p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  className="hidden"
                  onChange={handleFileChange}
                />
              </div>
            </div>

            {/* Column selector */}
            {columns.length > 0 && (
              <div className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm">
                <h2 className="font-semibold text-gray-800 mb-4 text-sm uppercase tracking-wide">Step 2 — Select description column</h2>
                <div className="flex items-center gap-4 flex-wrap">
                  <div className="flex-1 min-w-48">
                    <label className="block text-xs font-medium text-gray-500 mb-1.5">Column with product descriptions</label>
                    <select
                      value={selectedCol}
                      onChange={(e) => setSelectedCol(e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                    >
                      {columns.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                  <div className="text-xs text-gray-400 pt-5">
                    {rawRows.length.toLocaleString()} rows detected
                  </div>
                </div>

                {selectedCol && rawRows.slice(0, 3).map((r, i) => (
                  <div key={i} className="mt-2 text-xs text-gray-500 font-mono bg-gray-50 rounded px-3 py-1.5">
                    {String(r[selectedCol] ?? "").slice(0, 80) || <em className="text-gray-300">empty</em>}
                  </div>
                ))}
              </div>
            )}

            {/* Process button */}
            {columns.length > 0 && (
              <div className="flex items-center gap-4">
                <button
                  onClick={handleBulkProcess}
                  disabled={bulkLoading || !selectedCol}
                  className="px-8 py-3 bg-gray-900 text-white rounded-xl text-sm font-medium hover:bg-gray-700 disabled:opacity-40 transition"
                >
                  {bulkLoading ? "Processing…" : `Process ${rawRows.length.toLocaleString()} rows →`}
                </button>
                {bulkLoading && (
                  <div className="flex items-center gap-3 text-sm text-gray-500">
                    <div className="w-32 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500 rounded-full transition-all duration-300"
                        style={{ width: progress.total ? `${(progress.done / progress.total) * 100}%` : "0%" }}
                      />
                    </div>
                    <span>{progress.done.toLocaleString()} / {progress.total.toLocaleString()} processed</span>
                  </div>
                )}
              </div>
            )}

            {bulkError && (
              <div className="p-4 bg-red-50 border border-red-100 text-red-600 text-sm rounded-xl">{bulkError}</div>
            )}

            {/* Stats bar */}
            {bulkStats && (
              <div className="grid grid-cols-3 gap-4">
                {[
                  { label: "Total", value: bulkStats.total, color: "text-gray-700" },
                  { label: "Matched", value: bulkStats.matched, color: "text-emerald-600" },
                  { label: "Unmatched", value: bulkStats.unmatched, color: "text-red-500" },
                ].map((s) => (
                  <div key={s.label} className="bg-white border border-gray-100 rounded-2xl p-5 text-center shadow-sm">
                    <div className={`text-3xl font-bold ${s.color}`}>{s.value.toLocaleString()}</div>
                    <div className="text-xs text-gray-400 mt-1 font-medium">{s.label}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Results table */}
            {bulkResults.length > 0 && (
              <div className="bg-white border border-gray-100 rounded-2xl shadow-sm overflow-hidden">
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-50">
                  <h2 className="font-semibold text-gray-800 text-sm">
                    Results
                    {bulkLoading && (
                      <span className="ml-2 text-xs text-blue-500 font-normal">— live updating…</span>
                    )}
                  </h2>
                  <button
                    onClick={handleDownload}
                    disabled={bulkLoading}
                    className="flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-lg text-xs font-medium hover:bg-emerald-700 disabled:opacity-40 transition"
                  >
                    <span>⬇</span> Download .xlsx
                  </button>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-gray-50 text-xs font-medium text-gray-500 uppercase tracking-wide">
                        <th className="px-4 py-3 text-left">#</th>
                        <th className="px-4 py-3 text-left">Description</th>
                        <th className="px-4 py-3 text-left">HSN Code</th>
                        <th className="px-4 py-3 text-left">Matched Description</th>
                        <th className="px-4 py-3 text-left">GST%</th>
                        <th className="px-4 py-3 text-left">Confidence</th>
                        <th className="px-4 py-3 text-left">Method</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {pageSlice.map((r, i) => {
                        const rowNum = page * PAGE_SIZE + i + 1;
                        const isError = !!r.error;
                        const isUnmatched = !r.hsn_code && !isError;
                        return (
                          <tr
                            key={rowNum}
                            className={`transition hover:bg-gray-50/60 ${
                              isError ? "bg-red-50/40" : isUnmatched ? "bg-amber-50/30" : ""
                            }`}
                          >
                            <td className="px-4 py-3 text-gray-400 text-xs">{rowNum}</td>
                            <td className="px-4 py-3 max-w-xs">
                              <span className="text-gray-700 text-xs line-clamp-2">{r.query}</span>
                            </td>
                            <td className="px-4 py-3">
                              {r.hsn_code ? (
                                /* FIX: display zero-padded HSN code in table */
                                <span className="font-mono font-semibold text-blue-600 text-sm">{padHsn(r.hsn_code)}</span>
                              ) : (
                                <span className="text-gray-300 text-xs italic">{isError ? "error" : "—"}</span>
                              )}
                            </td>
                            <td className="px-4 py-3 max-w-xs">
                              <span className="text-gray-500 text-xs line-clamp-2">
                                {isError ? (
                                  <span className="text-red-500">{r.error}</span>
                                ) : (
                                  r.description ?? "—"
                                )}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-gray-600 text-xs font-medium">
                              {r.gst_rate != null ? `${r.gst_rate}%` : "—"}
                            </td>
                            <td className="px-4 py-3">
                              {r.hsn_code && !isError ? (
                                <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full border ${CONFIDENCE_COLOR[r.confidence_label]}`}>
                                  <span className={`w-1.5 h-1.5 rounded-full ${CONFIDENCE_DOT[r.confidence_label]}`} />
                                  {r.confidence_label} · {Math.round(r.confidence * 100)}%
                                </span>
                              ) : (
                                <span className="text-gray-300 text-xs">—</span>
                              )}
                            </td>
                            <td className="px-4 py-3">
                              <span className="text-xs text-gray-400 font-mono">{r.match_method}</span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between px-6 py-4 border-t border-gray-50">
                    <span className="text-xs text-gray-400">
                      Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, bulkResults.length)} of {bulkResults.length.toLocaleString()}
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setPage(Math.max(0, page - 1))}
                        disabled={page === 0}
                        className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-30 transition"
                      >
                        ← Prev
                      </button>
                      <span className="px-3 py-1.5 text-xs text-gray-500">
                        {page + 1} / {totalPages}
                      </span>
                      <button
                        onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                        disabled={page >= totalPages - 1}
                        className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-30 transition"
                      >
                        Next →
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {bulkResults.length === 0 && !bulkLoading && !bulkError && columns.length === 0 && (
              <div className="text-center py-16 text-gray-400">
                <div className="text-5xl mb-4">📊</div>
                <p className="text-sm">Upload an Excel or CSV file to get started</p>
                <p className="text-xs mt-2 text-gray-300">Supports .xlsx, .xls, and .csv formats</p>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

  query: string;
  hsn_code?: string;
  description?: string;
  gst_rate?: number;
  confidence: number;
  confidence_label: "high" | "medium" | "low";
  match_method: string;
  alternatives: { hsn_code: string; description: string; gst_rate: number; confidence: number }[];
  error?: string;
}

interface BatchResponse {
  results: HSNBatchResult[];
  total: number;
  matched: number;
  unmatched: number;
}

// ── Constants ─────────────────────────────────────────────────────────────────
const CONFIDENCE_COLOR: Record<string, string> = {
  high:   "bg-emerald-50 text-emerald-700 border-emerald-200",
  medium: "bg-amber-50 text-amber-700 border-amber-200",
  low:    "bg-red-50 text-red-600 border-red-200",
};

const CONFIDENCE_DOT: Record<string, string> = {
  high:   "bg-emerald-500",
  medium: "bg-amber-400",
  low:    "bg-red-400",
};

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const PAGE_SIZE = 20;

// ── Main component ─────────────────────────────────────────────────────────────
export default function Dashboard() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auth
  const [user, setUser] = useState<UserOut | null>(null);

  // Mode: "single" | "bulk"
  const [mode, setMode] = useState<"single" | "bulk">("single");

  // Single mode
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [singleLoading, setSingleLoading] = useState(false);
  const [singleError, setSingleError] = useState("");

  // Bulk mode
  const [fileName, setFileName] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [selectedCol, setSelectedCol] = useState("");
  const [rawRows, setRawRows] = useState<Record<string, unknown>[]>([]);
  const [bulkResults, setBulkResults] = useState<HSNBatchResult[]>([]);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkError, setBulkError] = useState("");
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [page, setPage] = useState(0);
  const [bulkStats, setBulkStats] = useState<{ matched: number; unmatched: number; total: number } | null>(null);

  useEffect(() => {
    if (!localStorage.getItem("access_token")) { router.replace("/login"); return; }
    authApi.me().then(setUser).catch(() => router.replace("/login"));
  }, []);

  // ── Single predict ──────────────────────────────────────────────────────────
  async function handlePredict(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSingleError(""); setSingleLoading(true); setResult(null);
    try {
      setResult(await hsnApi.predict(query));
    } catch (err: unknown) {
      setSingleError(err instanceof Error ? err.message : "Prediction failed");
    } finally { setSingleLoading(false); }
  }

  // ── File upload ─────────────────────────────────────────────────────────────
  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setBulkResults([]);
    setBulkError("");
    setBulkStats(null);
    setPage(0);

    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const data = ev.target?.result;
        const wb = XLSX.read(data, { type: "binary" });
        const ws = wb.Sheets[wb.SheetNames[0]];
        const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: "" });
        if (rows.length === 0) { setBulkError("File is empty or unreadable."); return; }
        const cols = Object.keys(rows[0]);
        setColumns(cols);
        setSelectedCol(cols[0]);
        setRawRows(rows);
      } catch {
        setBulkError("Could not parse file. Please upload a valid .xlsx or .csv.");
      }
    };
    reader.readAsBinaryString(file);
  }

  // ── Batch process ───────────────────────────────────────────────────────────
  const handleBulkProcess = useCallback(async () => {
    if (!selectedCol || rawRows.length === 0) return;
    setBulkLoading(true);
    setBulkError("");
    setBulkResults([]);
    setBulkStats(null);
    setPage(0);

    const descriptions = rawRows.map((r) => String(r[selectedCol] ?? "").trim()).filter(Boolean);
    const CHUNK = 50;
    const allResults: HSNBatchResult[] = [];
    setProgress({ done: 0, total: descriptions.length });

    const token = localStorage.getItem("access_token") ?? "";

    try {
      for (let i = 0; i < descriptions.length; i += CHUNK) {
        const chunk = descriptions.slice(i, i + CHUNK);
        const res = await fetch(`${BASE_URL}/hsn/batch`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ queries: chunk }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: "Unknown error" }));
          throw new Error(err.detail ?? `HTTP ${res.status}`);
        }
        const data: BatchResponse = await res.json();
        allResults.push(...data.results);
        setProgress({ done: Math.min(i + CHUNK, descriptions.length), total: descriptions.length });
        setBulkResults([...allResults]);
      }
      const matched = allResults.filter((r) => r.hsn_code && !r.error).length;
      setBulkStats({ matched, unmatched: allResults.length - matched, total: allResults.length });
    } catch (err: unknown) {
      setBulkError(err instanceof Error ? err.message : "Batch processing failed");
    } finally {
      setBulkLoading(false);
    }
  }, [selectedCol, rawRows]);

  // ── Download results ────────────────────────────────────────────────────────
  function handleDownload() {
    if (bulkResults.length === 0) return;
    const rows = bulkResults.map((r) => ({
      "Product Description": r.query,
      "HSN Code": r.hsn_code ?? "",
      "Matched Description": r.description ?? "",
      "GST Rate (%)": r.gst_rate ?? "",
      "Confidence": `${Math.round(r.confidence * 100)}%`,
      "Confidence Label": r.confidence_label,
      "Match Method": r.match_method,
      "Alt 1 HSN": r.alternatives[0]?.hsn_code ?? "",
      "Alt 1 Desc": r.alternatives[0]?.description ?? "",
      "Alt 2 HSN": r.alternatives[1]?.hsn_code ?? "",
      "Alt 2 Desc": r.alternatives[1]?.description ?? "",
      "Error": r.error ?? "",
    }));
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "HSN Results");

    // Column widths
    ws["!cols"] = [
      { wch: 40 }, { wch: 12 }, { wch: 40 }, { wch: 14 },
      { wch: 12 }, { wch: 16 }, { wch: 14 },
      { wch: 12 }, { wch: 30 }, { wch: 12 }, { wch: 30 }, { wch: 20 },
    ];
    XLSX.writeFile(wb, `hsn_results_${Date.now()}.xlsx`);
  }

  function signOut() { localStorage.clear(); router.push("/login"); }

  // ── Paginated slice ─────────────────────────────────────────────────────────
  const pageSlice = bulkResults.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages = Math.ceil(bulkResults.length / PAGE_SIZE);

  // ──────────────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Nav */}
      <nav className="bg-white border-b border-gray-100 px-8 py-4">
        <div className="max-w-5xl mx-auto flex justify-between items-center">
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

      <main className="max-w-5xl mx-auto px-8 py-10">
        {/* Header + mode toggle */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 mb-1">HSN Code Lookup</h1>
            <p className="text-gray-500 text-sm">Classify products to their GST HSN codes instantly</p>
          </div>
          <div className="flex items-center bg-gray-100 rounded-xl p-1 gap-1">
            {(["single", "bulk"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-5 py-2 rounded-lg text-sm font-medium transition ${
                  mode === m
                    ? "bg-white text-gray-900 shadow-sm"
                    : "text-gray-500 hover:text-gray-700"
                }`}
              >
                {m === "single" ? "Single" : "Bulk / Excel"}
              </button>
            ))}
          </div>
        </div>

        {/* ── Single mode ── */}
        {mode === "single" && (
          <div>
            <form onSubmit={handlePredict} className="flex gap-3 mb-8">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="e.g. laptop computer, cotton shirt, steel pipes, mobile phone..."
                className="flex-1 px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              />
              <button
                type="submit"
                disabled={singleLoading || !query.trim()}
                className="px-6 py-3 bg-gray-900 text-white rounded-xl text-sm font-medium hover:bg-gray-700 disabled:opacity-40 transition whitespace-nowrap"
              >
                {singleLoading ? "Classifying…" : "Classify →"}
              </button>
            </form>

            {singleError && (
              <div className="mb-6 p-4 bg-red-50 border border-red-100 text-red-600 text-sm rounded-xl">{singleError}</div>
            )}

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

            {!result && !singleLoading && (
              <div className="text-center py-16 text-gray-400">
                <div className="text-5xl mb-4">🔍</div>
                <p className="text-sm">Enter a product description above to get started</p>
              </div>
            )}
          </div>
        )}

        {/* ── Bulk mode ── */}
        {mode === "bulk" && (
          <div className="space-y-6">
            {/* Upload card */}
            <div className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm">
              <h2 className="font-semibold text-gray-800 mb-4 text-sm uppercase tracking-wide">Step 1 — Upload file</h2>
              <div
                onClick={() => fileInputRef.current?.click()}
                className="border-2 border-dashed border-gray-200 rounded-xl p-8 text-center cursor-pointer hover:border-blue-300 hover:bg-blue-50/30 transition group"
              >
                <div className="text-3xl mb-3">📁</div>
                <p className="text-sm font-medium text-gray-700 group-hover:text-blue-700 transition">
                  {fileName ? fileName : "Click to upload .xlsx or .csv"}
                </p>
                <p className="text-xs text-gray-400 mt-1">Max 500 rows per batch</p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  className="hidden"
                  onChange={handleFileChange}
                />
              </div>
            </div>

            {/* Column selector */}
            {columns.length > 0 && (
              <div className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm">
                <h2 className="font-semibold text-gray-800 mb-4 text-sm uppercase tracking-wide">Step 2 — Select description column</h2>
                <div className="flex items-center gap-4 flex-wrap">
                  <div className="flex-1 min-w-48">
                    <label className="block text-xs font-medium text-gray-500 mb-1.5">Column with product descriptions</label>
                    <select
                      value={selectedCol}
                      onChange={(e) => setSelectedCol(e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                    >
                      {columns.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                  <div className="text-xs text-gray-400 pt-5">
                    {rawRows.length.toLocaleString()} rows detected
                  </div>
                </div>

                {/* Preview of first 3 values */}
                {selectedCol && rawRows.slice(0, 3).map((r, i) => (
                  <div key={i} className="mt-2 text-xs text-gray-500 font-mono bg-gray-50 rounded px-3 py-1.5">
                    {String(r[selectedCol] ?? "").slice(0, 80) || <em className="text-gray-300">empty</em>}
                  </div>
                ))}
              </div>
            )}

            {/* Process button */}
            {columns.length > 0 && (
              <div className="flex items-center gap-4">
                <button
                  onClick={handleBulkProcess}
                  disabled={bulkLoading || !selectedCol}
                  className="px-8 py-3 bg-gray-900 text-white rounded-xl text-sm font-medium hover:bg-gray-700 disabled:opacity-40 transition"
                >
                  {bulkLoading ? "Processing…" : `Process ${rawRows.length.toLocaleString()} rows →`}
                </button>
                {bulkLoading && (
                  <div className="flex items-center gap-3 text-sm text-gray-500">
                    <div className="w-32 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500 rounded-full transition-all duration-300"
                        style={{ width: progress.total ? `${(progress.done / progress.total) * 100}%` : "0%" }}
                      />
                    </div>
                    <span>{progress.done.toLocaleString()} / {progress.total.toLocaleString()} processed</span>
                  </div>
                )}
              </div>
            )}

            {bulkError && (
              <div className="p-4 bg-red-50 border border-red-100 text-red-600 text-sm rounded-xl">{bulkError}</div>
            )}

            {/* Stats bar */}
            {bulkStats && (
              <div className="grid grid-cols-3 gap-4">
                {[
                  { label: "Total", value: bulkStats.total, color: "text-gray-700" },
                  { label: "Matched", value: bulkStats.matched, color: "text-emerald-600" },
                  { label: "Unmatched", value: bulkStats.unmatched, color: "text-red-500" },
                ].map((s) => (
                  <div key={s.label} className="bg-white border border-gray-100 rounded-2xl p-5 text-center shadow-sm">
                    <div className={`text-3xl font-bold ${s.color}`}>{s.value.toLocaleString()}</div>
                    <div className="text-xs text-gray-400 mt-1 font-medium">{s.label}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Results table */}
            {bulkResults.length > 0 && (
              <div className="bg-white border border-gray-100 rounded-2xl shadow-sm overflow-hidden">
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-50">
                  <h2 className="font-semibold text-gray-800 text-sm">
                    Results
                    {bulkLoading && (
                      <span className="ml-2 text-xs text-blue-500 font-normal">— live updating…</span>
                    )}
                  </h2>
                  <button
                    onClick={handleDownload}
                    disabled={bulkLoading}
                    className="flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-lg text-xs font-medium hover:bg-emerald-700 disabled:opacity-40 transition"
                  >
                    <span>⬇</span> Download .xlsx
                  </button>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-gray-50 text-xs font-medium text-gray-500 uppercase tracking-wide">
                        <th className="px-4 py-3 text-left">#</th>
                        <th className="px-4 py-3 text-left">Description</th>
                        <th className="px-4 py-3 text-left">HSN Code</th>
                        <th className="px-4 py-3 text-left">Matched Description</th>
                        <th className="px-4 py-3 text-left">GST%</th>
                        <th className="px-4 py-3 text-left">Confidence</th>
                        <th className="px-4 py-3 text-left">Method</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {pageSlice.map((r, i) => {
                        const rowNum = page * PAGE_SIZE + i + 1;
                        const isError = !!r.error;
                        const isUnmatched = !r.hsn_code && !isError;
                        return (
                          <tr
                            key={rowNum}
                            className={`transition hover:bg-gray-50/60 ${
                              isError ? "bg-red-50/40" : isUnmatched ? "bg-amber-50/30" : ""
                            }`}
                          >
                            <td className="px-4 py-3 text-gray-400 text-xs">{rowNum}</td>
                            <td className="px-4 py-3 max-w-xs">
                              <span className="text-gray-700 text-xs line-clamp-2">{r.query}</span>
                            </td>
                            <td className="px-4 py-3">
                              {r.hsn_code ? (
                                <span className="font-mono font-semibold text-blue-600 text-sm">{r.hsn_code}</span>
                              ) : (
                                <span className="text-gray-300 text-xs italic">{isError ? "error" : "—"}</span>
                              )}
                            </td>
                            <td className="px-4 py-3 max-w-xs">
                              <span className="text-gray-500 text-xs line-clamp-2">
                                {isError ? (
                                  <span className="text-red-500">{r.error}</span>
                                ) : (
                                  r.description ?? "—"
                                )}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-gray-600 text-xs font-medium">
                              {r.gst_rate != null ? `${r.gst_rate}%` : "—"}
                            </td>
                            <td className="px-4 py-3">
                              {r.hsn_code && !isError ? (
                                <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full border ${CONFIDENCE_COLOR[r.confidence_label]}`}>
                                  <span className={`w-1.5 h-1.5 rounded-full ${CONFIDENCE_DOT[r.confidence_label]}`} />
                                  {r.confidence_label} · {Math.round(r.confidence * 100)}%
                                </span>
                              ) : (
                                <span className="text-gray-300 text-xs">—</span>
                              )}
                            </td>
                            <td className="px-4 py-3">
                              <span className="text-xs text-gray-400 font-mono">{r.match_method}</span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between px-6 py-4 border-t border-gray-50">
                    <span className="text-xs text-gray-400">
                      Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, bulkResults.length)} of {bulkResults.length.toLocaleString()}
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setPage(Math.max(0, page - 1))}
                        disabled={page === 0}
                        className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-30 transition"
                      >
                        ← Prev
                      </button>
                      <span className="px-3 py-1.5 text-xs text-gray-500">
                        {page + 1} / {totalPages}
                      </span>
                      <button
                        onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                        disabled={page >= totalPages - 1}
                        className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-30 transition"
                      >
                        Next →
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {bulkResults.length === 0 && !bulkLoading && !bulkError && columns.length === 0 && (
              <div className="text-center py-16 text-gray-400">
                <div className="text-5xl mb-4">📊</div>
                <p className="text-sm">Upload an Excel or CSV file to get started</p>
                <p className="text-xs mt-2 text-gray-300">Supports .xlsx, .xls, and .csv formats</p>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
