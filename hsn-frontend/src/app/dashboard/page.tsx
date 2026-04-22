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

function padHsn(code: string | undefined): string {
  if (!code) return "";
  const t = code.trim();
  return /^\d+$/.test(t) ? t.padStart(8, "0") : t;
}

function ConfidencePill({ label, value }: { label: string; value: number }) {
  const styles: Record<string, { bg: string; border: string; color: string; dot: string }> = {
    high:   { bg: "rgba(29,90,60,0.2)",  border: "rgba(45,120,80,0.4)",  color: "#4db87a", dot: "#2d9060" },
    medium: { bg: "rgba(120,90,20,0.2)", border: "rgba(160,120,30,0.4)", color: "#c8a060", dot: "#a07830" },
    low:    { bg: "rgba(120,30,30,0.2)", border: "rgba(160,50,50,0.4)",  color: "#c07070", dot: "#903030" },
  };
  const s = styles[label] ?? styles.low;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, background: s.bg, border: `1px solid ${s.border}`, color: s.color, padding: "0.2rem 0.55rem", borderRadius: 100, fontSize: "0.72rem", fontWeight: 600, fontFamily: "'DM Mono', monospace", whiteSpace: "nowrap" }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: s.dot, flexShrink: 0 }} />
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
    body { margin: 0; background: #060b18; }
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: #0a1020; }
    ::-webkit-scrollbar-thumb { background: #1a2840; border-radius: 3px; }
    .search-input {
      flex: 1; background: rgba(6,11,24,0.8); border: 1px solid #1a2840;
      color: #c8d4e8; padding: 0.7rem 1rem; border-radius: 7px;
      font-size: 0.875rem; font-family: 'DM Sans', sans-serif;
      outline: none; transition: border-color 0.2s, box-shadow 0.2s; min-width: 0;
    }
    .search-input::placeholder { color: #2e4060; }
    .search-input:focus { border-color: #2d4a7a; box-shadow: 0 0 0 3px rgba(45,74,122,0.15); }
    .btn-primary {
      background: linear-gradient(135deg, #1e3a6e 0%, #2d5aa0 100%);
      color: #a8c4f0; border: 1px solid #2d4a7a;
      padding: 0.7rem 1.25rem; border-radius: 7px; font-size: 0.8rem;
      font-weight: 600; cursor: pointer; font-family: 'DM Sans', sans-serif;
      display: inline-flex; align-items: center; gap: 0.4rem;
      transition: all 0.2s; letter-spacing: 0.02em; white-space: nowrap;
    }
    .btn-primary:hover:not(:disabled) { background: linear-gradient(135deg, #243f77 0%, #3463ae 100%); color: #c8d8f8; box-shadow: 0 0 16px rgba(45,90,160,0.25); }
    .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
    .btn-ghost {
      background: transparent; color: #4e6480; border: 1px solid #1a2840;
      padding: 0.7rem 1rem; border-radius: 7px; font-size: 0.8rem;
      font-weight: 500; cursor: pointer; font-family: 'DM Sans', sans-serif;
      display: inline-flex; align-items: center; gap: 0.4rem;
      transition: all 0.2s;
    }
    .btn-ghost:hover { border-color: #2d4a7a; color: #8aaccc; }
    .btn-success {
      background: linear-gradient(135deg, #163d2a, #1e5e3a);
      color: #4db87a; border: 1px solid rgba(45,120,80,0.4);
      padding: 0.6rem 1rem; border-radius: 7px; font-size: 0.78rem;
      font-weight: 600; cursor: pointer; font-family: 'DM Sans', sans-serif;
      display: inline-flex; align-items: center; gap: 0.4rem;
      transition: all 0.2s; letter-spacing: 0.02em;
    }
    .btn-success:hover:not(:disabled) { background: linear-gradient(135deg, #1a4a32, #246e44); }
    .btn-success:disabled { opacity: 0.4; cursor: not-allowed; }
    .card { background: rgba(10,16,30,0.95); border: 1px solid #1a2840; border-radius: 10px; position: relative; overflow: hidden; }
    .card-top-line { position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(90,140,230,0.25), transparent); }
    .tab { background: transparent; border: none; cursor: pointer; font-family: 'DM Sans', sans-serif; font-size: 0.82rem; font-weight: 500; padding: 0.5rem 1rem; border-radius: 5px; display: inline-flex; align-items: center; gap: 0.375rem; transition: all 0.2s; }
    .tab.active { background: rgba(30,58,110,0.5); color: #8ab8e8; border: 1px solid rgba(45,74,122,0.5); }
    .tab.inactive { color: #4e6480; }
    .tab.inactive:hover { color: #7a9ab8; }
    .select-input {
      background: rgba(6,11,24,0.8); border: 1px solid #1a2840; color: #c8d4e8;
      padding: 0.6rem 0.875rem; border-radius: 6px; font-size: 0.82rem;
      font-family: 'DM Sans', sans-serif; outline: none; cursor: pointer;
    }
    .select-input:focus { border-color: #2d4a7a; }
    .upload-zone {
      border: 2px dashed #1a2840; border-radius: 8px; padding: 2.5rem 1.5rem;
      text-align: center; cursor: pointer; transition: all 0.2s;
    }
    .upload-zone:hover { border-color: #2d4a7a; background: rgba(30,58,110,0.05); }
    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; font-size: 0.68rem; font-weight: 600; color: #3a5070; text-transform: uppercase; letter-spacing: 0.08em; padding: 0.625rem 0.875rem; border-bottom: 1px solid #0e1828; background: rgba(6,11,24,0.5); }
    td { padding: 0.6rem 0.875rem; border-bottom: 1px solid #0e1828; font-size: 0.8rem; color: #7a90b0; vertical-align: middle; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(30,58,110,0.06); }
    .hsn-code-big { font-family: 'DM Mono', monospace; color: #5b8fe8; }
    .hsn-code-sm { font-family: 'DM Mono', monospace; color: #5b8fe8; font-size: 0.85rem; font-weight: 500; }
    .section-label { font-size: 0.7rem; font-weight: 600; color: #3a5070; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 0.75rem; }
    .mono { font-family: 'DM Mono', monospace; }
  `;

  return (
    <div style={{ minHeight: "100vh", background: "#060b18", color: "#c8d4e8", fontFamily: "'DM Sans', sans-serif" }}>
      <style>{sharedStyles}</style>

      {/* Nav */}
      <nav style={{ borderBottom: "1px solid #0e1828", background: "rgba(6,11,24,0.98)", backdropFilter: "blur(12px)", position: "sticky", top: 0, zIndex: 50 }}>
        <div style={{ maxWidth: 1140, margin: "0 auto", padding: "0 1.5rem", height: 56, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <div style={{ width: 26, height: 26, background: "linear-gradient(135deg, #1e3a6e, #3d6db5)", borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <BarChart3 size={13} color="#8ab4e8" />
            </div>
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: "0.9rem", color: "#b8cce0" }}>HSN Classifier</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "1.25rem" }}>
            <span style={{ fontSize: "0.75rem", color: "#3a5070", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user?.email}</span>
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
            <h1 style={{ fontFamily: "'Syne', sans-serif", fontSize: "1.5rem", fontWeight: 700, color: "#c8d4e8", marginBottom: "0.25rem", letterSpacing: "-0.01em" }}>
              HSN Code Lookup
            </h1>
            <p style={{ fontSize: "0.78rem", color: "#3a5070" }}>Classify products to their GST HSN codes instantly</p>
          </div>
          {/* Mode tabs */}
          <div style={{ display: "flex", gap: "0.375rem", background: "rgba(6,11,24,0.8)", border: "1px solid #1a2840", borderRadius: 8, padding: "0.25rem" }}>
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
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", background: "rgba(120,30,30,0.15)", border: "1px solid rgba(160,50,50,0.3)", color: "#c07070", fontSize: "0.8rem", padding: "0.625rem 0.875rem", borderRadius: 7, marginBottom: "1rem" }}>
                <AlertCircle size={14} /> {singleError}
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
                      <div style={{ color: "#6b84a6", fontSize: "0.875rem", marginTop: "0.5rem", maxWidth: 480 }}>{result.top_match.description}</div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.5rem" }}>
                      <ConfidencePill label={result.confidence_label} value={result.confidence} />
                      {result.needs_review && (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem", fontSize: "0.7rem", color: "#c8a060", background: "rgba(120,90,20,0.15)", border: "1px solid rgba(160,120,30,0.3)", padding: "0.2rem 0.55rem", borderRadius: 100 }}>
                          <Clock size={10} /> Review recommended
                        </span>
                      )}
                    </div>
                  </div>
                  <div style={{ borderTop: "1px solid #0e1828", paddingTop: "0.875rem", display: "flex", gap: "1.5rem", flexWrap: "wrap" }}>
                    {[
                      { label: "Score", val: result.top_match.score.toFixed(3) },
                      { label: "Method", val: result.top_match.method },
                      { label: "Latency", val: `${result.processing_time_ms.toFixed(0)}ms` },
                    ].map((m) => (
                      <div key={m.label}>
                        <div style={{ fontSize: "0.65rem", color: "#3a5070", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>{m.label}</div>
                        <div className="mono" style={{ fontSize: "0.78rem", color: "#7a90b0" }}>{m.val}</div>
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
                            <td style={{ color: "#5a7a9a", maxWidth: 320 }}><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block" }}>{a.description}</span></td>
                            <td><span className="mono" style={{ fontSize: "0.75rem" }}>{(a.score * 100).toFixed(0)}%</span></td>
                            <td><span style={{ fontSize: "0.7rem", color: "#3a5070", fontFamily: "'DM Mono', monospace" }}>{a.method}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {!result && !singleLoading && (
              <div style={{ textAlign: "center", padding: "5rem 2rem", color: "#2e4060" }}>
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
                <Upload size={22} style={{ color: "#2d4a7a", marginBottom: "0.75rem" }} />
                <p style={{ fontSize: "0.85rem", color: "#4e6480", margin: "0 0 0.25rem", fontWeight: 500 }}>
                  {fileName || "Click to upload .xlsx or .csv"}
                </p>
                <p style={{ fontSize: "0.72rem", color: "#2e4060", margin: 0 }}>Max 500 rows per batch</p>
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
                  <span style={{ fontSize: "0.75rem", color: "#3a5070" }}>{rawRows.length.toLocaleString()} rows detected</span>
                </div>
                {selectedCol && rawRows.slice(0, 2).map((r, i) => (
                  <div key={i} className="mono" style={{ fontSize: "0.72rem", color: "#3a5070", background: "rgba(6,11,24,0.6)", border: "1px solid #0e1828", borderRadius: 5, padding: "0.4rem 0.75rem", marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
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
                    <div style={{ width: 140, height: 4, background: "#0e1828", borderRadius: 2, overflow: "hidden" }}>
                      <div style={{ height: "100%", background: "linear-gradient(90deg, #2d5aa0, #5b8fe8)", borderRadius: 2, width: `${(progress.done / progress.total) * 100}%`, transition: "width 0.3s" }} />
                    </div>
                    <span style={{ fontSize: "0.75rem", color: "#3a5070", fontFamily: "'DM Mono', monospace" }}>{progress.done}/{progress.total}</span>
                  </div>
                )}
              </div>
            )}

            {bulkError && (
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", background: "rgba(120,30,30,0.15)", border: "1px solid rgba(160,50,50,0.3)", color: "#c07070", fontSize: "0.8rem", padding: "0.75rem 1rem", borderRadius: 7 }}>
                <AlertCircle size={14} /> {bulkError}
              </div>
            )}

            {/* Stats */}
            {bulkStats && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.875rem" }}>
                {[
                  { label: "Total", val: bulkStats.total, color: "#c8d4e8", icon: <FileSpreadsheet size={14} /> },
                  { label: "Matched", val: bulkStats.matched, color: "#4db87a", icon: <CheckCircle2 size={14} /> },
                  { label: "Unmatched", val: bulkStats.unmatched, color: "#c07070", icon: <X size={14} /> },
                ].map((s) => (
                  <div key={s.label} className="card" style={{ padding: "1.25rem", textAlign: "center" }}>
                    <div className="card-top-line" />
                    <div style={{ display: "flex", justifyContent: "center", marginBottom: "0.5rem", color: s.color, opacity: 0.6 }}>{s.icon}</div>
                    <div className="mono" style={{ fontSize: "2rem", fontWeight: 500, color: s.color, lineHeight: 1 }}>{s.val.toLocaleString()}</div>
                    <div style={{ fontSize: "0.7rem", color: "#3a5070", textTransform: "uppercase", letterSpacing: "0.08em", marginTop: 4 }}>{s.label}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Results table */}
            {bulkResults.length > 0 && (
              <div className="card" style={{ overflow: "hidden" }}>
                <div className="card-top-line" />
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "1rem 1.25rem", borderBottom: "1px solid #0e1828" }}>
                  <div>
                    <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 600, fontSize: "0.85rem", color: "#b8cce0" }}>Results</span>
                    {bulkLoading && <span style={{ marginLeft: "0.625rem", fontSize: "0.72rem", color: "#3a6090" }}>— updating…</span>}
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
                            <td style={{ color: "#2e4060", fontFamily: "'DM Mono', monospace", fontSize: "0.72rem" }}>{rowNum}</td>
                            <td style={{ maxWidth: 240 }}>
                              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block", color: "#5a7a9a", fontSize: "0.78rem" }}>{r.query}</span>
                            </td>
                            <td>
                              {r.hsn_code
                                ? <span className="hsn-code-sm">{padHsn(r.hsn_code)}</span>
                                : <span style={{ color: "#2e4060", fontSize: "0.72rem", fontStyle: "italic" }}>{r.error ? "error" : "—"}</span>
                              }
                            </td>
                            <td style={{ maxWidth: 220 }}>
                              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block", fontSize: "0.75rem" }}>
                                {r.error ? <span style={{ color: "#c07070" }}>{r.error}</span> : (r.description ?? "—")}
                              </span>
                            </td>
                            <td className="mono" style={{ fontSize: "0.75rem" }}>{r.gst_rate != null ? `${r.gst_rate}%` : "—"}</td>
                            <td>{r.hsn_code && !r.error ? <ConfidencePill label={r.confidence_label} value={r.confidence} /> : <span style={{ color: "#2e4060" }}>—</span>}</td>
                            <td><span className="mono" style={{ fontSize: "0.68rem", color: "#2e4060" }}>{r.match_method}</span></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {totalPages > 1 && (
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0.875rem 1.25rem", borderTop: "1px solid #0e1828" }}>
                    <span style={{ fontSize: "0.72rem", color: "#2e4060", fontFamily: "'DM Mono', monospace" }}>
                      {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, bulkResults.length)} of {bulkResults.length.toLocaleString()}
                    </span>
                    <div style={{ display: "flex", gap: "0.375rem", alignItems: "center" }}>
                      <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0} className="btn-ghost" style={{ padding: "0.375rem 0.625rem" }}>
                        <ChevronLeft size={14} />
                      </button>
                      <span style={{ fontSize: "0.72rem", color: "#3a5070", fontFamily: "'DM Mono', monospace", padding: "0 0.375rem" }}>{page + 1}/{totalPages}</span>
                      <button onClick={() => setPage(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1} className="btn-ghost" style={{ padding: "0.375rem 0.625rem" }}>
                        <ChevronRight size={14} />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {bulkResults.length === 0 && !bulkLoading && !bulkError && columns.length === 0 && (
              <div style={{ textAlign: "center", padding: "4rem 2rem", color: "#2e4060" }}>
                <FileSpreadsheet size={36} style={{ marginBottom: "1rem", opacity: 0.35 }} />
                <p style={{ fontSize: "0.85rem", marginBottom: "0.375rem" }}>Upload an Excel or CSV file to get started</p>
                <p style={{ fontSize: "0.75rem", color: "#243040" }}>Supports .xlsx, .xls, and .csv formats</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <footer style={{ borderTop: "1px solid #0e1828", padding: "1rem 1.5rem", marginTop: "2rem" }}>
        <div style={{ maxWidth: 1140, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: "0.7rem", color: "#243040" }}>HSN Classifier — AI-powered GST compliance</span>
          <span style={{ fontSize: "0.7rem", color: "#2e3d52" }}>
            Developer: <span style={{ color: "#7a8060" }}>DhanushRaghav</span>
          </span>
        </div>
      </footer>
    </div>
  );
}
