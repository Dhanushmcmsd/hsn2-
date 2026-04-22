"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { hsnApi, authApi, type PredictResponse, type UserOut } from "@/lib/api";
import * as XLSX from "xlsx";
import {
  BarChart3, Search, Upload, Download, LogOut, FileSpreadsheet,
  ChevronRight, ChevronLeft, AlertCircle, CheckCircle2, Clock, X, Loader2
} from "lucide-react";

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
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const PAGE_SIZE = 20;

// Color tokens from palette
// #F5F8F3 — near-white (bg/surfaces)
// #CEDDFA — light periwinkle (secondary surfaces, borders)
// #0180EB — vivid blue (primary accent)
// #001F54 — deep navy (dark bg, text)

function padHsn(code: string | undefined): string {
  if (!code) return "";
  const t = code.trim();
  return /^\d+$/.test(t) ? t.padStart(8, "0") : t;
}

function ConfidencePill({ label, value }: { label: string; value: number }) {
  const styles: Record<string, { bg: string; border: string; color: string; dot: string }> = {
    high:   { bg: "rgba(1,128,235,0.12)",   border: "rgba(1,128,235,0.35)",  color: "#0180EB", dot: "#0180EB" },
    medium: { bg: "rgba(206,221,250,0.18)",  border: "rgba(206,221,250,0.5)", color: "#4a7fc1", dot: "#4a7fc1" },
    low:    { bg: "rgba(0,31,84,0.15)",       border: "rgba(0,31,84,0.3)",    color: "#6a8aad", dot: "#6a8aad" },
  };
  const s = styles[label] ?? styles.low;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, background: s.bg, border: `1px solid ${s.border}`, color: s.color, padding: "0.2rem 0.55rem", borderRadius: 100, fontSize: "0.72rem", fontWeight: 600, fontFamily: "'DM Mono', monospace", whiteSpace: "nowrap", boxShadow: `0 0 8px ${s.bg}` }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: s.dot, flexShrink: 0, boxShadow: `0 0 4px ${s.dot}` }} />
      {label} · {Math.round(value * 100)}%
    </span>
  );
}

export default function Dashboard() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [user, setUser] = useState<UserOut | null>(null);
  const [mode, setMode] = useState<"single" | "bulk">("single");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [singleLoading, setSingleLoading] = useState(false);
  const [singleError, setSingleError] = useState("");
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

  async function handlePredict(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSingleError(""); setSingleLoading(true); setResult(null);
    try { setResult(await hsnApi.predict(query)); }
    catch (err: unknown) { setSingleError(err instanceof Error ? err.message : "Prediction failed"); }
    finally { setSingleLoading(false); }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name); setBulkResults([]); setBulkError(""); setBulkStats(null); setPage(0);
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const data = ev.target?.result;
        const wb = XLSX.read(data, { type: "binary" });
        const ws = wb.Sheets[wb.SheetNames[0]];
        const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: "" });
        if (rows.length === 0) { setBulkError("File is empty or unreadable."); return; }
        const cols = Object.keys(rows[0]);
        setColumns(cols); setSelectedCol(cols[0]); setRawRows(rows);
      } catch { setBulkError("Could not parse file. Upload a valid .xlsx or .csv."); }
    };
    reader.readAsBinaryString(file);
  }

  const handleBulkProcess = useCallback(async () => {
    if (!selectedCol || rawRows.length === 0) return;
    setBulkLoading(true); setBulkError(""); setBulkResults([]); setBulkStats(null); setPage(0);
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
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ queries: chunk }),
        });
        if (!res.ok) { const err = await res.json().catch(() => ({ detail: "Unknown" })); throw new Error(err.detail ?? `HTTP ${res.status}`); }
        const data: BatchResponse = await res.json();
        allResults.push(...data.results);
        setProgress({ done: Math.min(i + CHUNK, descriptions.length), total: descriptions.length });
        setBulkResults([...allResults]);
      }
      const matched = allResults.filter((r) => r.hsn_code && !r.error).length;
      setBulkStats({ matched, unmatched: allResults.length - matched, total: allResults.length });
    } catch (err: unknown) {
      setBulkError(err instanceof Error ? err.message : "Batch processing failed");
    } finally { setBulkLoading(false); }
  }, [selectedCol, rawRows]);

  function handleDownload() {
    if (bulkResults.length === 0) return;
    const rows = bulkResults.map((r) => ({
      "Product Description": r.query,
      "HSN Code": padHsn(r.hsn_code),
      "Matched Description": r.description ?? "",
      "GST Rate (%)": r.gst_rate ?? "",
      "Confidence": `${Math.round(r.confidence * 100)}%`,
      "Confidence Label": r.confidence_label,
      "Match Method": r.match_method,
      "Alt 1 HSN": padHsn(r.alternatives[0]?.hsn_code),
      "Alt 1 Desc": r.alternatives[0]?.description ?? "",
      "Error": r.error ?? "",
    }));
    const ws = XLSX.utils.json_to_sheet(rows);
    ws["!cols"] = [{ wch: 40 }, { wch: 12 }, { wch: 40 }, { wch: 14 }, { wch: 12 }, { wch: 16 }, { wch: 14 }, { wch: 12 }, { wch: 30 }, { wch: 20 }];
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "HSN Results");
    XLSX.writeFile(wb, `hsn_results_${Date.now()}.xlsx`);
  }

  function signOut() { localStorage.clear(); router.push("/login"); }

  const pageSlice = bulkResults.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages = Math.ceil(bulkResults.length / PAGE_SIZE);

  const sharedStyles = `
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=Syne:wght@600;700;800&family=DM+Mono:wght@400;500&display=swap');
    * { box-sizing: border-box; }
    body { margin: 0; background: #001F54; }
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: #001030; }
    ::-webkit-scrollbar-thumb { background: #0180EB44; border-radius: 3px; }
    .search-input {
      flex: 1; background: rgba(0,31,84,0.6); border: 1px solid #CEDDFA44;
      color: #F5F8F3; padding: 0.7rem 1rem; border-radius: 7px;
      font-size: 0.875rem; font-family: 'DM Sans', sans-serif;
      outline: none; transition: border-color 0.2s, box-shadow 0.2s; min-width: 0;
    }
    .search-input::placeholder { color: #CEDDFA55; }
    .search-input:focus {
      border-color: #0180EB;
      box-shadow: 0 0 0 3px rgba(1,128,235,0.2), 0 0 12px rgba(1,128,235,0.15);
    }
    .btn-primary {
      background: linear-gradient(135deg, #0180EB 0%, #0a60c0 100%);
      color: #F5F8F3; border: 1px solid #0180EB;
      padding: 0.7rem 1.25rem; border-radius: 7px; font-size: 0.8rem;
      font-weight: 600; cursor: pointer; font-family: 'DM Sans', sans-serif;
      display: inline-flex; align-items: center; gap: 0.4rem;
      transition: all 0.2s; letter-spacing: 0.02em; white-space: nowrap;
      box-shadow: 0 0 14px rgba(1,128,235,0.35), inset 0 1px 0 rgba(245,248,243,0.15);
    }
    .btn-primary:hover:not(:disabled) {
      background: linear-gradient(135deg, #1a90ff 0%, #0070d0 100%);
      box-shadow: 0 0 22px rgba(1,128,235,0.55), inset 0 1px 0 rgba(245,248,243,0.2);
      transform: translateY(-1px);
    }
    .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; box-shadow: none; }
    .btn-ghost {
      background: rgba(206,221,250,0.06); color: #CEDDFA99; border: 1px solid #CEDDFA33;
      padding: 0.7rem 1rem; border-radius: 7px; font-size: 0.8rem;
      font-weight: 500; cursor: pointer; font-family: 'DM Sans', sans-serif;
      display: inline-flex; align-items: center; gap: 0.4rem;
      transition: all 0.2s;
    }
    .btn-ghost:hover {
      border-color: #0180EB88;
      color: #F5F8F3;
      background: rgba(1,128,235,0.1);
      box-shadow: 0 0 8px rgba(1,128,235,0.15);
    }
    .btn-success {
      background: linear-gradient(135deg, #003d7a, #0180EB);
      color: #F5F8F3; border: 1px solid rgba(1,128,235,0.5);
      padding: 0.6rem 1rem; border-radius: 7px; font-size: 0.78rem;
      font-weight: 600; cursor: pointer; font-family: 'DM Sans', sans-serif;
      display: inline-flex; align-items: center; gap: 0.4rem;
      transition: all 0.2s; letter-spacing: 0.02em;
      box-shadow: 0 0 12px rgba(1,128,235,0.3), inset 0 1px 0 rgba(245,248,243,0.1);
    }
    .btn-success:hover:not(:disabled) {
      background: linear-gradient(135deg, #004d99, #1a90ff);
      box-shadow: 0 0 20px rgba(1,128,235,0.5), inset 0 1px 0 rgba(245,248,243,0.2);
    }
    .btn-success:disabled { opacity: 0.4; cursor: not-allowed; box-shadow: none; }
    .card {
      background: rgba(0,31,84,0.85);
      border: 1px solid #CEDDFA22;
      border-radius: 10px; position: relative; overflow: hidden;
      backdrop-filter: blur(8px);
    }
    .card-top-line { position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(1,128,235,0.5), transparent); }
    .tab { background: transparent; border: none; cursor: pointer; font-family: 'DM Sans', sans-serif; font-size: 0.82rem; font-weight: 500; padding: 0.5rem 1rem; border-radius: 5px; display: inline-flex; align-items: center; gap: 0.375rem; transition: all 0.2s; }
    .tab.active {
      background: rgba(1,128,235,0.2);
      color: #F5F8F3;
      border: 1px solid rgba(1,128,235,0.5);
      box-shadow: 0 0 10px rgba(1,128,235,0.2), inset 0 1px 0 rgba(206,221,250,0.1);
    }
    .tab.inactive { color: #CEDDFA66; }
    .tab.inactive:hover { color: #CEDDFA; background: rgba(206,221,250,0.06); }
    .select-input {
      background: rgba(0,31,84,0.7); border: 1px solid #CEDDFA33; color: #F5F8F3;
      padding: 0.6rem 0.875rem; border-radius: 6px; font-size: 0.82rem;
      font-family: 'DM Sans', sans-serif; outline: none; cursor: pointer;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .select-input:focus {
      border-color: #0180EB;
      box-shadow: 0 0 8px rgba(1,128,235,0.25);
    }
    .upload-zone {
      border: 2px dashed #CEDDFA33; border-radius: 8px; padding: 2.5rem 1.5rem;
      text-align: center; cursor: pointer; transition: all 0.2s;
    }
    .upload-zone:hover {
      border-color: #0180EB88;
      background: rgba(1,128,235,0.06);
      box-shadow: inset 0 0 20px rgba(1,128,235,0.05);
    }
    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; font-size: 0.68rem; font-weight: 600; color: #CEDDFA55; text-transform: uppercase; letter-spacing: 0.08em; padding: 0.625rem 0.875rem; border-bottom: 1px solid #CEDDFA15; background: rgba(0,20,50,0.5); }
    td { padding: 0.6rem 0.875rem; border-bottom: 1px solid #CEDDFA10; font-size: 0.8rem; color: #CEDDFA99; vertical-align: middle; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(1,128,235,0.06); }
    .hsn-code-big { font-family: 'DM Mono', monospace; color: #0180EB; text-shadow: 0 0 12px rgba(1,128,235,0.4); }
    .hsn-code-sm { font-family: 'DM Mono', monospace; color: #0180EB; font-size: 0.85rem; font-weight: 500; text-shadow: 0 0 8px rgba(1,128,235,0.3); }
    .section-label { font-size: 0.7rem; font-weight: 600; color: #CEDDFA55; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 0.75rem; }
    .mono { font-family: 'DM Mono', monospace; }
    @keyframes spin { to { transform: rotate(360deg); } }
  `;

  return (
    <div style={{ minHeight: "100vh", background: "#001F54", color: "#F5F8F3", fontFamily: "'DM Sans', sans-serif" }}>
      <style>{sharedStyles}</style>

      {/* Nav */}
      <nav style={{ borderBottom: "1px solid #CEDDFA18", background: "rgba(0,20,50,0.97)", backdropFilter: "blur(16px)", position: "sticky", top: 0, zIndex: 50, boxShadow: "0 1px 20px rgba(1,128,235,0.1)" }}>
        <div style={{ maxWidth: 1140, margin: "0 auto", padding: "0 1.5rem", height: 56, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <div style={{ width: 26, height: 26, background: "linear-gradient(135deg, #0180EB, #0a60c0)", borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 0 10px rgba(1,128,235,0.5)" }}>
              <BarChart3 size={13} color="#F5F8F3" />
            </div>
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: "0.9rem", color: "#F5F8F3" }}>HSN Classifier</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "1.25rem" }}>
            <span style={{ fontSize: "0.75rem", color: "#CEDDFA55", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user?.email}</span>
            <button onClick={signOut} className="btn-ghost" style={{ padding: "0.4rem 0.75rem", fontSize: "0.75rem" }}>
              <LogOut size={13} /> Sign out
            </button>
          </div>
        </div>
      </nav>

      {/* Main */}
      <div style={{ maxWidth: 1140, margin: "0 auto", padding: "2rem 1.5rem" }}>

        {/* Page header */}
        <div style={{ marginBottom: "1.75rem", display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem" }}>
          <div>
            <h1 style={{ fontFamily: "'Syne', sans-serif", fontSize: "1.5rem", fontWeight: 700, color: "#F5F8F3", marginBottom: "0.25rem", letterSpacing: "-0.01em" }}>
              HSN Code Lookup
            </h1>
            <p style={{ fontSize: "0.78rem", color: "#CEDDFA66" }}>Classify products to their GST HSN codes instantly</p>
          </div>
          {/* Mode tabs */}
          <div style={{ display: "flex", gap: "0.375rem", background: "rgba(0,20,50,0.8)", border: "1px solid #CEDDFA22", borderRadius: 8, padding: "0.25rem" }}>
            <button onClick={() => setMode("single")} className={`tab ${mode === "single" ? "active" : "inactive"}`}>
              <Search size={13} /> Single
            </button>
            <button onClick={() => setMode("bulk")} className={`tab ${mode === "bulk" ? "active" : "inactive"}`}>
              <FileSpreadsheet size={13} /> Bulk / Excel
            </button>
          </div>
        </div>

        {/* ── SINGLE MODE ── */}
        {mode === "single" && (
          <div>
            <form onSubmit={handlePredict} style={{ display: "flex", gap: "0.625rem", marginBottom: "1.5rem" }}>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Enter product description — e.g. VKC DL3323 BLUE LADIES 06"
                className="search-input"
              />
              <button type="submit" disabled={singleLoading || !query.trim()} className="btn-primary">
                {singleLoading ? <><Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> Classifying</> : <><Search size={14} /> Classify</>}
              </button>
            </form>

            {singleError && (
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", background: "rgba(0,31,84,0.8)", border: "1px solid rgba(1,128,235,0.3)", color: "#CEDDFA", fontSize: "0.8rem", padding: "0.625rem 0.875rem", borderRadius: 7, marginBottom: "1rem" }}>
                <AlertCircle size={14} color="#0180EB" /> {singleError}
              </div>
            )}

            {result && (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.875rem" }}>
                {/* Top match card */}
                <div className="card" style={{ padding: "1.75rem" }}>
                  <div className="card-top-line" />
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", marginBottom: "1.25rem" }}>
                    <div>
                      <div className="section-label">Top match</div>
                      <div className="hsn-code-big" style={{ fontSize: "2.5rem", fontWeight: 500, letterSpacing: "0.04em", lineHeight: 1 }}>{padHsn(result.top_match.hsn_code)}</div>
                      <div style={{ color: "#CEDDFA88", fontSize: "0.875rem", marginTop: "0.5rem", maxWidth: 480 }}>{result.top_match.description}</div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.5rem" }}>
                      <ConfidencePill label={result.confidence_label} value={result.confidence} />
                      {result.needs_review && (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem", fontSize: "0.7rem", color: "#CEDDFA", background: "rgba(206,221,250,0.1)", border: "1px solid rgba(206,221,250,0.25)", padding: "0.2rem 0.55rem", borderRadius: 100 }}>
                          <Clock size={10} /> Review recommended
                        </span>
                      )}
                    </div>
                  </div>
                  <div style={{ borderTop: "1px solid #CEDDFA15", paddingTop: "0.875rem", display: "flex", gap: "1.5rem", flexWrap: "wrap" }}>
                    {[
                      { label: "Score", val: result.top_match.score.toFixed(3) },
                      { label: "Method", val: result.top_match.method },
                      { label: "Latency", val: `${result.processing_time_ms.toFixed(0)}ms` },
                    ].map((m) => (
                      <div key={m.label}>
                        <div style={{ fontSize: "0.65rem", color: "#CEDDFA44", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>{m.label}</div>
                        <div className="mono" style={{ fontSize: "0.78rem", color: "#CEDDFA99" }}>{m.val}</div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Alternatives */}
                {result.alternatives.length > 0 && (
                  <div className="card" style={{ overflow: "hidden" }}>
                    <div className="card-top-line" />
                    <div style={{ padding: "1rem 1.25rem 0.75rem" }}>
                      <div className="section-label">Alternative matches</div>
                    </div>
                    <table>
                      <thead>
                        <tr>
                          <th>HSN Code</th>
                          <th>Description</th>
                          <th>Score</th>
                          <th>Method</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.alternatives.map((a) => (
                          <tr key={a.hsn_code}>
                            <td><span className="hsn-code-sm">{padHsn(a.hsn_code)}</span></td>
                            <td style={{ color: "#CEDDFA77", maxWidth: 320 }}><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block" }}>{a.description}</span></td>
                            <td><span className="mono" style={{ fontSize: "0.75rem" }}>{(a.score * 100).toFixed(0)}%</span></td>
                            <td><span style={{ fontSize: "0.7rem", color: "#CEDDFA44", fontFamily: "'DM Mono', monospace" }}>{a.method}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {!result && !singleLoading && (
              <div style={{ textAlign: "center", padding: "5rem 2rem", color: "#CEDDFA33" }}>
                <Search size={32} style={{ marginBottom: "1rem", opacity: 0.4 }} />
                <p style={{ fontSize: "0.85rem" }}>Enter a product description to classify it</p>
              </div>
            )}
          </div>
        )}

        {/* ── BULK MODE ── */}
        {mode === "bulk" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            {/* Upload */}
            <div className="card" style={{ padding: "1.5rem" }}>
              <div className="card-top-line" />
              <div className="section-label">Step 1 — Upload file</div>
              <div className="upload-zone" onClick={() => fileInputRef.current?.click()}>
                <Upload size={22} style={{ color: "#0180EB", marginBottom: "0.75rem", filter: "drop-shadow(0 0 6px rgba(1,128,235,0.5))" }} />
                <p style={{ fontSize: "0.85rem", color: "#CEDDFA88", margin: "0 0 0.25rem", fontWeight: 500 }}>
                  {fileName || "Click to upload .xlsx or .csv"}
                </p>
                <p style={{ fontSize: "0.72rem", color: "#CEDDFA44", margin: 0 }}>Max 500 rows per batch</p>
                <input ref={fileInputRef} type="file" accept=".xlsx,.xls,.csv" style={{ display: "none" }} onChange={handleFileChange} />
              </div>
            </div>

            {/* Column selector */}
            {columns.length > 0 && (
              <div className="card" style={{ padding: "1.5rem" }}>
                <div className="card-top-line" />
                <div className="section-label">Step 2 — Select description column</div>
                <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap", marginBottom: "0.875rem" }}>
                  <select value={selectedCol} onChange={(e) => setSelectedCol(e.target.value)} className="select-input">
                    {columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                  <span style={{ fontSize: "0.75rem", color: "#CEDDFA55" }}>{rawRows.length.toLocaleString()} rows detected</span>
                </div>
                {selectedCol && rawRows.slice(0, 2).map((r, i) => (
                  <div key={i} className="mono" style={{ fontSize: "0.72rem", color: "#CEDDFA44", background: "rgba(0,15,40,0.6)", border: "1px solid #CEDDFA15", borderRadius: 5, padding: "0.4rem 0.75rem", marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {String(r[selectedCol] ?? "").slice(0, 90) || "—"}
                  </div>
                ))}
              </div>
            )}

            {/* Process */}
            {columns.length > 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
                <button onClick={handleBulkProcess} disabled={bulkLoading || !selectedCol} className="btn-primary" style={{ padding: "0.75rem 1.5rem" }}>
                  {bulkLoading ? <><Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> Processing…</> : <><FileSpreadsheet size={14} /> Process {rawRows.length.toLocaleString()} rows</>}
                </button>
                {bulkLoading && progress.total > 0 && (
                  <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                    <div style={{ width: 140, height: 4, background: "#CEDDFA15", borderRadius: 2, overflow: "hidden" }}>
                      <div style={{ height: "100%", background: "linear-gradient(90deg, #0180EB, #60b4ff)", borderRadius: 2, width: `${(progress.done / progress.total) * 100}%`, transition: "width 0.3s", boxShadow: "0 0 8px rgba(1,128,235,0.6)" }} />
                    </div>
                    <span style={{ fontSize: "0.75rem", color: "#CEDDFA55", fontFamily: "'DM Mono', monospace" }}>{progress.done}/{progress.total}</span>
                  </div>
                )}
              </div>
            )}

            {bulkError && (
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", background: "rgba(0,31,84,0.8)", border: "1px solid rgba(1,128,235,0.3)", color: "#CEDDFA", fontSize: "0.8rem", padding: "0.75rem 1rem", borderRadius: 7 }}>
                <AlertCircle size={14} color="#0180EB" /> {bulkError}
              </div>
            )}

            {/* Stats */}
            {bulkStats && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.875rem" }}>
                {[
                  { label: "Total", val: bulkStats.total, color: "#F5F8F3", icon: <FileSpreadsheet size={14} />, glow: "#CEDDFA" },
                  { label: "Matched", val: bulkStats.matched, color: "#0180EB", icon: <CheckCircle2 size={14} />, glow: "#0180EB" },
                  { label: "Unmatched", val: bulkStats.unmatched, color: "#CEDDFA", icon: <X size={14} />, glow: "#CEDDFA" },
                ].map((s) => (
                  <div key={s.label} className="card" style={{ padding: "1.25rem", textAlign: "center" }}>
                    <div className="card-top-line" />
                    <div style={{ display: "flex", justifyContent: "center", marginBottom: "0.5rem", color: s.color, opacity: 0.7, filter: `drop-shadow(0 0 4px ${s.glow}66)` }}>{s.icon}</div>
                    <div className="mono" style={{ fontSize: "2rem", fontWeight: 500, color: s.color, lineHeight: 1, textShadow: `0 0 16px ${s.glow}44` }}>{s.val.toLocaleString()}</div>
                    <div style={{ fontSize: "0.7rem", color: "#CEDDFA44", textTransform: "uppercase", letterSpacing: "0.08em", marginTop: 4 }}>{s.label}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Results table */}
            {bulkResults.length > 0 && (
              <div className="card" style={{ overflow: "hidden" }}>
                <div className="card-top-line" />
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "1rem 1.25rem", borderBottom: "1px solid #CEDDFA15" }}>
                  <div>
                    <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 600, fontSize: "0.85rem", color: "#F5F8F3" }}>Results</span>
                    {bulkLoading && <span style={{ marginLeft: "0.625rem", fontSize: "0.72rem", color: "#0180EB88" }}>— updating…</span>}
                  </div>
                  <button onClick={handleDownload} disabled={bulkLoading} className="btn-success">
                    <Download size={13} /> Download .xlsx
                  </button>
                </div>

                <div style={{ overflowX: "auto" }}>
                  <table>
                    <thead>
                      <tr>
                        <th style={{ width: 42 }}>#</th>
                        <th>Description</th>
                        <th>HSN Code</th>
                        <th>Matched As</th>
                        <th>GST%</th>
                        <th>Confidence</th>
                        <th>Method</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pageSlice.map((r, i) => {
                        const rowNum = page * PAGE_SIZE + i + 1;
                        return (
                          <tr key={rowNum}>
                            <td style={{ color: "#CEDDFA33", fontFamily: "'DM Mono', monospace", fontSize: "0.72rem" }}>{rowNum}</td>
                            <td style={{ maxWidth: 240 }}>
                              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block", color: "#CEDDFA77", fontSize: "0.78rem" }}>{r.query}</span>
                            </td>
                            <td>
                              {r.hsn_code
                                ? <span className="hsn-code-sm">{padHsn(r.hsn_code)}</span>
                                : <span style={{ color: "#CEDDFA33", fontSize: "0.72rem", fontStyle: "italic" }}>{r.error ? "error" : "—"}</span>
                              }
                            </td>
                            <td style={{ maxWidth: 220 }}>
                              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block", fontSize: "0.75rem" }}>
                                {r.error ? <span style={{ color: "#CEDDFA66" }}>{r.error}</span> : (r.description ?? "—")}
                              </span>
                            </td>
                            <td className="mono" style={{ fontSize: "0.75rem" }}>{r.gst_rate != null ? `${r.gst_rate}%` : "—"}</td>
                            <td>{r.hsn_code && !r.error ? <ConfidencePill label={r.confidence_label} value={r.confidence} /> : <span style={{ color: "#CEDDFA22" }}>—</span>}</td>
                            <td><span className="mono" style={{ fontSize: "0.68rem", color: "#CEDDFA33" }}>{r.match_method}</span></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {totalPages > 1 && (
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0.875rem 1.25rem", borderTop: "1px solid #CEDDFA15" }}>
                    <span style={{ fontSize: "0.72rem", color: "#CEDDFA33", fontFamily: "'DM Mono', monospace" }}>
                      {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, bulkResults.length)} of {bulkResults.length.toLocaleString()}
                    </span>
                    <div style={{ display: "flex", gap: "0.375rem", alignItems: "center" }}>
                      <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0} className="btn-ghost" style={{ padding: "0.375rem 0.625rem" }}>
                        <ChevronLeft size={14} />
                      </button>
                      <span style={{ fontSize: "0.72rem", color: "#CEDDFA55", fontFamily: "'DM Mono', monospace", padding: "0 0.375rem" }}>{page + 1}/{totalPages}</span>
                      <button onClick={() => setPage(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1} className="btn-ghost" style={{ padding: "0.375rem 0.625rem" }}>
                        <ChevronRight size={14} />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {bulkResults.length === 0 && !bulkLoading && !bulkError && columns.length === 0 && (
              <div style={{ textAlign: "center", padding: "4rem 2rem", color: "#CEDDFA33" }}>
                <FileSpreadsheet size={36} style={{ marginBottom: "1rem", opacity: 0.35 }} />
                <p style={{ fontSize: "0.85rem", marginBottom: "0.375rem" }}>Upload an Excel or CSV file to get started</p>
                <p style={{ fontSize: "0.75rem", color: "#CEDDFA22" }}>Supports .xlsx, .xls, and .csv formats</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <footer style={{ borderTop: "1px solid #CEDDFA15", padding: "1rem 1.5rem", marginTop: "2rem" }}>
        <div style={{ maxWidth: 1140, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: "0.7rem", color: "#CEDDFA33" }}>HSN Classifier — AI-powered GST compliance</span>
          <span style={{ fontSize: "0.7rem", color: "#CEDDFA44" }}>
            Developer: <span style={{ color: "#0180EB", textShadow: "0 0 8px rgba(1,128,235,0.4)" }}>DhanushRaghav</span>
          </span>
        </div>
      </footer>
    </div>
  );
}
