"use client";
import { useState, useRef, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import Papa from "papaparse";
import readXlsxFile from "read-excel-file/browser";
import {
  authApi,
  authStorage,
  hsnApi,
  type BulkResult,
  type PredictResponse,
} from "@/lib/api";
import { LogOut } from "lucide-react";
import { LogoAnimation } from "@/components/LogoAnimation";

const PAGE_SIZE = 20;
type DashboardMode = "single" | "bulk";
type ConfidenceLabel = "high" | "medium" | "low";
type RowData = Record<string, string>;
type BulkStats = { matched: number; unmatched: number; total: number };
type PredictLikeResponse = PredictResponse & { gst_rate?: number | null };
type FloatIconShape = "invoice" | "rupee" | "barcode" | "gst" | "sheet";

type FloatIconProps = {
  shape: FloatIconShape;
  x: number;
  y: number;
  size: number;
  delay: number;
  dur: number;
};

type ConfPillProps = {
  label: ConfidenceLabel;
  value: number;
};

type GstPillProps = {
  rate: number | null | undefined;
};

type ProcessStepProps = {
  label: string;
  done: boolean;
  active: boolean;
};

function padHsn(code: string | null | undefined) {
  if (!code) return "";
  const t = code.trim();
  return /^\d+$/.test(t) ? t.padStart(8, "0") : t;
}

function normalizeCellValue(value: unknown): string {
  if (value == null) return "";
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value).trim();
}

function pickDefaultColumn(columnNames: string[]): string {
  return (
    columnNames.find((column) => /product|description|item|name/i.test(column)) ??
    columnNames[0] ??
    ""
  );
}

function normalizeParsedRows(parsedRows: Array<Record<string, unknown>>): RowData[] {
  return parsedRows
    .map((row) =>
      Object.fromEntries(
        Object.entries(row).map(([key, value]) => [String(key).trim(), normalizeCellValue(value)])
      )
    )
    .filter((row) => Object.values(row).some((value) => String(value).trim() !== ""));
}

async function parseCsvFile(file: File): Promise<RowData[]> {
  const text = await file.text();
  const parsed = Papa.parse<Record<string, unknown>>(text, {
    header: true,
    skipEmptyLines: true,
    transformHeader: (header: string) => String(header).trim(),
  });
  if (parsed.errors.length > 0) {
    throw new Error(parsed.errors[0]?.message || "Unable to parse the uploaded CSV file.");
  }
  return normalizeParsedRows(parsed.data);
}

async function parseXlsxFile(file: File): Promise<RowData[]> {
  const rows = (await readXlsxFile(file, { dateFormat: "YYYY-MM-DD" }) as unknown) as unknown[][];
  if (!rows.length) {
    throw new Error("The uploaded file does not contain any sheets.");
  }

  const [headerRow, ...dataRows] = rows;
  const headers = (headerRow || []).map((cell: unknown, index: number) => {
    const normalized = normalizeCellValue(cell);
    return normalized || `COLUMN_${index + 1}`;
  });

  const parsedRows = dataRows
    .filter((row: unknown[]) => row.some((cell: unknown) => normalizeCellValue(cell) !== ""))
    .map((row: unknown[]) =>
      Object.fromEntries(
        headers.map((header: string, index: number) => [header, row[index] ?? ""])
      )
    );

  return normalizeParsedRows(parsedRows);
}

function toBulkResult(query: string, response: PredictLikeResponse): BulkResult {
  return {
    query,
    hsn_code: response.top_match?.hsn_code ?? "",
    description:
      response.top_match?.full_description ??
      response.top_match?.description ??
      "",
    gst_rate: response.gst_rate ?? response.top_match?.gst_rate ?? null,
    confidence: response.confidence ?? response.top_match?.score ?? 0,
    confidence_label: response.confidence_label ?? "low",
    match_method: response.top_match?.method ?? "",
    alternatives: response.alternatives ?? [],
    needs_review: Boolean(response.needs_review),
    error: "",
  };
}

function toFailedBulkResult(query: string, error: unknown): BulkResult {
  const message = error instanceof Error ? error.message : "Prediction failed";
  return {
    query,
    hsn_code: "",
    description: "",
    gst_rate: null,
    confidence: 0,
    confidence_label: "low",
    match_method: "error",
    alternatives: [],
    needs_review: true,
    error: message,
  };
}

function escapeCsvValue(value: unknown) {
  const text = value == null ? "" : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

// ── Floating ambient icons (Indian GST context) ──────────────────────────────
const FLOAT_ICONS: FloatIconProps[] = [
  { shape: "invoice", x: 8, y: 15, size: 38, delay: 0, dur: 22 },
  { shape: "rupee",   x: 88, y: 8,  size: 28, delay: 3, dur: 18 },
  { shape: "barcode", x: 5,  y: 72, size: 44, delay: 6, dur: 25 },
  { shape: "gst",     x: 82, y: 65, size: 34, delay: 1, dur: 20 },
  { shape: "sheet",   x: 50, y: 5,  size: 30, delay: 8, dur: 28 },
  { shape: "rupee",   x: 18, y: 88, size: 22, delay: 4, dur: 16 },
  { shape: "invoice", x: 72, y: 85, size: 36, delay: 9, dur: 24 },
  { shape: "barcode", x: 92, y: 40, size: 26, delay: 2, dur: 19 },
];

function FloatingIcon({ shape, x, y, size, delay, dur }: FloatIconProps) {
  const paths: Record<FloatIconShape, JSX.Element> = {
    invoice: (
      <g>
        <rect x="2" y="1" width="20" height="26" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5"/>
        <line x1="6" y1="8" x2="18" y2="8" stroke="currentColor" strokeWidth="1.2"/>
        <line x1="6" y1="12" x2="18" y2="12" stroke="currentColor" strokeWidth="1.2"/>
        <line x1="6" y1="16" x2="13" y2="16" stroke="currentColor" strokeWidth="1.2"/>
        <line x1="6" y1="20" x2="16" y2="20" stroke="currentColor" strokeWidth="1.2"/>
      </g>
    ),
    rupee: (
      <g>
        <text x="4" y="22" fontSize="22" fill="currentColor" fontFamily="serif" fontWeight="bold">₹</text>
      </g>
    ),
    barcode: (
      <g>
        {[0,3,5,8,10,13,16,19,21].map((bx,i) => (
          <rect key={i} x={bx} y="4" width={i%3===0?2:1.5} height="16" fill="currentColor"/>
        ))}
        <text x="2" y="26" fontSize="6" fill="currentColor" fontFamily="monospace">084930271</text>
      </g>
    ),
    gst: (
      <g>
        <text x="1" y="17" fontSize="13" fill="currentColor" fontFamily="sans-serif" fontWeight="700" letterSpacing="1">GST</text>
        <line x1="0" y1="20" x2="26" y2="20" stroke="currentColor" strokeWidth="1"/>
        <text x="2" y="28" fontSize="7" fill="currentColor" fontFamily="monospace">HSN</text>
      </g>
    ),
    sheet: (
      <g>
        <rect x="1" y="1" width="22" height="22" rx="1" fill="none" stroke="currentColor" strokeWidth="1.2"/>
        {[5,9,13,17].map((ry,i) => (
          <line key={i} x1="1" y1={ry} x2="23" y2={ry} stroke="currentColor" strokeWidth="0.8"/>
        ))}
        {[7,13,19].map((rx,i) => (
          <line key={i} x1={rx} y1="1" x2={rx} y2="23" stroke="currentColor" strokeWidth="0.8"/>
        ))}
      </g>
    ),
  };

  return (
    <div style={{
      position: "absolute",
      left: `${x}%`,
      top: `${y}%`,
      width: size,
      height: size,
      color: "rgba(96,165,250,0.08)",
      animation: `floatDrift${delay%4} ${dur}s ease-in-out infinite`,
      animationDelay: `${delay}s`,
      pointerEvents: "none",
      filter: "blur(0.5px)",
    }}>
      <svg viewBox="0 0 28 28" width={size} height={size} style={{display:"block"}}>
        {paths[shape]}
      </svg>
    </div>
  );
}

// ── Confidence pill ──────────────────────────────────────────────────────────
function ConfPill({ label, value }: ConfPillProps) {
  const map: Record<ConfidenceLabel, { color: string; bg: string; border: string }> = {
    high:   { color: "#60a5fa", bg: "rgba(96,165,250,0.12)", border: "rgba(96,165,250,0.3)" },
    medium: { color: "#a78bfa", bg: "rgba(167,139,250,0.12)", border: "rgba(167,139,250,0.3)" },
    low:    { color: "#94a3b8", bg: "rgba(148,163,184,0.1)", border: "rgba(148,163,184,0.2)" },
  };
  const s = map[label] || map.low;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      background: s.bg, border: `1px solid ${s.border}`,
      color: s.color, padding: "3px 10px", borderRadius: 100,
      fontSize: "0.7rem", fontWeight: 600, fontFamily: "'DM Mono', monospace",
      whiteSpace: "nowrap",
    }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: s.color, flexShrink: 0 }} />
      {label} · {Math.round(value * 100)}%
    </span>
  );
}

// ── GST rate pill ────────────────────────────────────────────────────────────
function GstPill({ rate }: GstPillProps) {
  if (rate == null) return null;
  const colors = {
    0:  { color: "#94a3b8", bg: "rgba(148,163,184,0.1)", border: "rgba(148,163,184,0.25)" },
    5:  { color: "#4ade80", bg: "rgba(74,222,128,0.1)", border: "rgba(74,222,128,0.3)" },
    12: { color: "#fb923c", bg: "rgba(251,146,60,0.1)", border: "rgba(251,146,60,0.3)" },
    18: { color: "#f59e0b", bg: "rgba(245,158,11,0.1)", border: "rgba(245,158,11,0.3)" },
    28: { color: "#f87171", bg: "rgba(248,113,113,0.1)", border: "rgba(248,113,113,0.3)" },
  };
  const s = colors[rate as keyof typeof colors] || { color: "#a78bfa", bg: "rgba(167,139,250,0.1)", border: "rgba(167,139,250,0.3)" };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      background: s.bg, border: `1px solid ${s.border}`,
      color: s.color, padding: "3px 10px", borderRadius: 100,
      fontSize: "0.7rem", fontWeight: 600, fontFamily: "'DM Mono', monospace",
      whiteSpace: "nowrap",
    }}>
      <span style={{ fontSize: "0.65rem", opacity: 0.7 }}>₹</span>
      GST {rate}%
    </span>
  );
}

// ── Step indicator ───────────────────────────────────────────────────────────
function ProcessStep({ label, done, active }: ProcessStepProps) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.78rem",
      color: done ? "#60a5fa" : active ? "#e2e8f0" : "#475569",
      transition: "color 0.4s" }}>
      <div style={{
        width: 16, height: 16, borderRadius: "50%", flexShrink: 0,
        background: done ? "#60a5fa" : active ? "rgba(96,165,250,0.3)" : "rgba(148,163,184,0.15)",
        border: `1px solid ${done ? "#60a5fa" : active ? "rgba(96,165,250,0.6)" : "rgba(148,163,184,0.2)"}`,
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "all 0.4s",
      }}>
        {done && (
          <svg width="8" height="8" viewBox="0 0 8 8">
            <polyline points="1.5,4 3,5.5 6.5,2.5" stroke="white" strokeWidth="1.5" fill="none"/>
          </svg>
        )}
        {active && !done && <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#60a5fa", animation: "pulse 1s ease-in-out infinite" }} />}
      </div>
      {label}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────
export default function PremiumDashboard() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [mode, setMode] = useState<DashboardMode>("single");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<PredictLikeResponse | null>(null);
  const [singleLoading, setSingleLoading] = useState(false);
  const [singleError, setSingleError] = useState("");
  const [fileName, setFileName] = useState("");
  const [fileSize, setFileSize] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [selectedCol, setSelectedCol] = useState("");
  const [rawRows, setRawRows] = useState<RowData[]>([]);
  const [bulkResults, setBulkResults] = useState<BulkResult[]>([]);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkError, setBulkError] = useState("");
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [page, setPage] = useState(0);
  const [bulkStats, setBulkStats] = useState<BulkStats | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [processSteps, setProcessSteps] = useState<[boolean, boolean, boolean]>([false, false, false]);
  const [showFileSuccess, setShowFileSuccess] = useState(false);
  const [userInitial, setUserInitial] = useState("U");
  const [authReady, setAuthReady] = useState(false);

  const CSS = `
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Cabinet+Grotesk:wght@400;500;700;800&family=Instrument+Sans:wght@400;500;600&display=swap');

    *, *::before, *::after { box-sizing: border-box; }
    body { margin: 0; background: #020617; }

    @keyframes floatDrift0 {
      0%,100%{transform:translate(0,0) rotate(-2deg)}
      33%{transform:translate(8px,-12px) rotate(2deg)}
      66%{transform:translate(-6px,8px) rotate(-1deg)}
    }
    @keyframes floatDrift1 {
      0%,100%{transform:translate(0,0) rotate(1deg)}
      50%{transform:translate(-10px,-8px) rotate(-3deg)}
    }
    @keyframes floatDrift2 {
      0%,100%{transform:translate(0,0)}
      25%{transform:translate(6px,10px) rotate(2deg)}
      75%{transform:translate(-8px,-6px) rotate(-2deg)}
    }
    @keyframes floatDrift3 {
      0%,100%{transform:translate(0,0) rotate(-1deg)}
      40%{transform:translate(10px,-14px) rotate(3deg)}
      80%{transform:translate(-4px,6px) rotate(0deg)}
    }
    @keyframes blobDrift {
      0%,100%{transform:translate(0,0) scale(1)}
      50%{transform:translate(40px,30px) scale(1.08)}
    }
    @keyframes pulse {
      0%,100%{opacity:0.5;transform:scale(0.8)}
      50%{opacity:1;transform:scale(1)}
    }
    @keyframes shimmer {
      0%{transform:translateX(-100%)}
      100%{transform:translateX(100%)}
    }
    @keyframes fadeUp {
      from{opacity:0;transform:translateY(12px)}
      to{opacity:1;transform:translateY(0)}
    }
    @keyframes glow {
      0%,100%{box-shadow:0 0 20px rgba(96,165,250,0.2)}
      50%{box-shadow:0 0 40px rgba(96,165,250,0.4)}
    }
    @keyframes borderGlow {
      0%,100%{border-color:rgba(96,165,250,0.3)}
      50%{border-color:rgba(96,165,250,0.8)}
    }
    @keyframes checkPop {
      0%{transform:scale(0)}
      70%{transform:scale(1.2)}
      100%{transform:scale(1)}
    }
    @keyframes wave {
      0%,100%{transform:scaleY(1) skewX(-0.3deg)}
      50%{transform:scaleY(1.03) skewX(0.3deg)}
    }
    @keyframes spin {
      to{transform:rotate(360deg)}
    }
    @keyframes dotBounce {
      0%,80%,100%{transform:scale(0)}
      40%{transform:scale(1)}
    }
    @keyframes flagWave {
      0%,100%{transform:perspective(300px) rotateY(0deg) scaleX(1)}
      25%{transform:perspective(300px) rotateY(2deg) scaleX(0.98)}
      50%{transform:perspective(300px) rotateY(0deg) scaleX(1.01)}
      75%{transform:perspective(300px) rotateY(-2deg) scaleX(0.99)}
    }

    .glass-card {
      background: rgba(255,255,255,0.02);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1px solid rgba(255,255,255,0.07);
      border-radius: 20px;
    }
    .glass-card-bright {
      background: rgba(255,255,255,0.04);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 20px;
    }
    .input-field {
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.1);
      color: #e2e8f0;
      padding: 0.75rem 1.1rem;
      border-radius: 12px;
      font-size: 0.875rem;
      font-family: 'Instrument Sans', sans-serif;
      outline: none;
      transition: border-color 0.25s, box-shadow 0.25s, background 0.25s;
      width: 100%;
    }
    .input-field::placeholder{color:#475569}
    .input-field:focus{
      border-color: rgba(96,165,250,0.6);
      background: rgba(255,255,255,0.06);
      box-shadow: 0 0 0 3px rgba(96,165,250,0.12), 0 0 20px rgba(96,165,250,0.1);
    }
    .btn-primary {
      background: linear-gradient(135deg, #2563eb 0%, #3b82f6 100%);
      color: #fff;
      border: none;
      padding: 0.72rem 1.5rem;
      border-radius: 12px;
      font-size: 0.82rem;
      font-weight: 600;
      font-family: 'Instrument Sans', sans-serif;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      letter-spacing: 0.02em;
      transition: transform 0.2s, box-shadow 0.2s;
      box-shadow: 0 4px 24px rgba(37,99,235,0.4), 0 0 0 1px rgba(59,130,246,0.3) inset;
      white-space: nowrap;
    }
    .btn-primary:hover:not(:disabled){
      transform: translateY(-2px);
      box-shadow: 0 8px 32px rgba(37,99,235,0.55), 0 0 0 1px rgba(59,130,246,0.3) inset;
    }
    .btn-primary:disabled{opacity:0.4;cursor:not-allowed}
    .btn-ghost {
      background: rgba(255,255,255,0.04);
      color: #94a3b8;
      border: 1px solid rgba(255,255,255,0.08);
      padding: 0.65rem 1.1rem;
      border-radius: 10px;
      font-size: 0.78rem;
      font-family: 'Instrument Sans', sans-serif;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      transition: all 0.2s;
    }
    .btn-ghost:hover{background:rgba(255,255,255,0.08);color:#e2e8f0;border-color:rgba(96,165,250,0.4)}
    .tab-btn {
      background: transparent;
      border: none;
      cursor: pointer;
      font-family: 'Instrument Sans', sans-serif;
      font-size: 0.82rem;
      padding: 0.5rem 1.1rem;
      border-radius: 10px;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      transition: all 0.2s;
    }
    .tab-active {
      background: rgba(37,99,235,0.25);
      color: #93c5fd;
      border: 1px solid rgba(59,130,246,0.4);
      box-shadow: 0 0 16px rgba(37,99,235,0.2);
    }
    .tab-inactive{color:#475569;border:1px solid transparent}
    .tab-inactive:hover{color:#94a3b8;background:rgba(255,255,255,0.04)}
    .select-field {
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.1);
      color: #e2e8f0;
      padding: 0.65rem 0.9rem;
      border-radius: 10px;
      font-size: 0.82rem;
      font-family: 'Instrument Sans', sans-serif;
      outline: none;
      cursor: pointer;
    }
    .select-field:focus{border-color:rgba(96,165,250,0.5)}
    .data-table{width:100%;border-collapse:collapse}
    .data-table th{
      text-align:left;
      font-size:0.66rem;
      font-weight:600;
      color:#475569;
      text-transform:uppercase;
      letter-spacing:0.1em;
      padding:0.65rem 1rem;
      border-bottom:1px solid rgba(255,255,255,0.05);
      background:rgba(0,0,0,0.2);
    }
    .data-table td{
      padding:0.6rem 1rem;
      border-bottom:1px solid rgba(255,255,255,0.04);
      font-size:0.79rem;
      color:#64748b;
      vertical-align:middle;
    }
    .data-table tr:last-child td{border-bottom:none}
    .data-table tr:hover td{background:rgba(37,99,235,0.06)}
    .hsn-big{
      font-family:'DM Mono',monospace;
      color:#60a5fa;
      font-size:clamp(2.5rem,7vw,5rem);
      font-weight:400;
      letter-spacing:0.1em;
      line-height:1;
      text-shadow:0 0 40px rgba(96,165,250,0.5);
    }
    .hsn-sm{
      font-family:'DM Mono',monospace;
      color:#60a5fa;
      font-size:0.82rem;
      font-weight:500;
      letter-spacing:0.04em;
    }
    .lbl{
      font-size:0.68rem;
      font-weight:600;
      color:#334155;
      text-transform:uppercase;
      letter-spacing:0.1em;
      margin-bottom:0.6rem;
    }
    .upload-zone {
      border: 1.5px dashed rgba(96,165,250,0.25);
      border-radius: 16px;
      padding: 3.5rem 2rem;
      text-align: center;
      cursor: pointer;
      position: relative;
      overflow: hidden;
      transition: all 0.35s ease;
      background: rgba(37,99,235,0.02);
    }
    .upload-zone:hover, .upload-zone.drag {
      border-color: rgba(96,165,250,0.7);
      background: rgba(37,99,235,0.06);
      box-shadow: 0 0 40px rgba(37,99,235,0.12), inset 0 0 30px rgba(37,99,235,0.06);
      animation: borderGlow 2s ease-in-out infinite;
    }
    .upload-zone .corner{
      position:absolute;
      width:12px;height:12px;
      border-color:rgba(96,165,250,0.4);
      border-style:solid;
    }
    .upload-zone .c-tl{top:8px;left:8px;border-width:1.5px 0 0 1.5px;border-radius:4px 0 0 0}
    .upload-zone .c-tr{top:8px;right:8px;border-width:1.5px 1.5px 0 0;border-radius:0 4px 0 0}
    .upload-zone .c-bl{bottom:8px;left:8px;border-width:0 0 1.5px 1.5px;border-radius:0 0 0 4px}
    .upload-zone .c-br{bottom:8px;right:8px;border-width:0 1.5px 1.5px 0;border-radius:0 0 4px 0}
    .upload-icon-ring {
      width:60px;height:60px;
      margin:0 auto 1.5rem;
      border-radius:50%;
      background:rgba(37,99,235,0.1);
      border:1.5px solid rgba(96,165,250,0.3);
      display:flex;align-items:center;justify-content:center;
      animation:glow 3s ease-in-out infinite;
      box-shadow:0 0 24px rgba(37,99,235,0.2);
    }
    .stat-card{
      background:rgba(255,255,255,0.02);
      border:1px solid rgba(255,255,255,0.06);
      border-radius:14px;
      padding:1.25rem;
      text-align:center;
      position:relative;
      overflow:hidden;
    }
    .stat-card::before{
      content:'';
      position:absolute;top:0;left:0;right:0;height:1px;
      background:linear-gradient(90deg,transparent,rgba(96,165,250,0.4),transparent);
    }
    ::-webkit-scrollbar{width:4px;height:4px}
    ::-webkit-scrollbar-track{background:transparent}
    ::-webkit-scrollbar-thumb{background:rgba(96,165,250,0.2);border-radius:4px}
    .usage-bar{
      height:3px;background:rgba(255,255,255,0.08);border-radius:4px;overflow:hidden;
    }
    .usage-fill{
      height:100%;
      background:linear-gradient(90deg,#2563eb,#3b82f6);
      border-radius:4px;
      width:24%;
      transition:width 0.5s ease;
    }
    .loading-dots span {
      display:inline-block;
      width:6px;height:6px;
      border-radius:50%;
      background:#60a5fa;
      margin:0 2px;
    }
    .loading-dots span:nth-child(1){animation:dotBounce 1.4s ease-in-out 0s infinite}
    .loading-dots span:nth-child(2){animation:dotBounce 1.4s ease-in-out 0.2s infinite}
    .loading-dots span:nth-child(3){animation:dotBounce 1.4s ease-in-out 0.4s infinite}

    /* Indian flag watermark */
    .india-flag-watermark {
      position:absolute;
      width:160px;
      height:96px;
      border-radius:4px;
      overflow:hidden;
      opacity:0.055;
      filter:blur(1px) saturate(0.6);
      animation:flagWave 8s ease-in-out infinite;
      pointer-events:none;
    }
    .india-flag-watermark::before,
    .india-flag-watermark::after {
      content:'';
      position:absolute;
      left:0;right:0;
      height:33.33%;
    }
    .flag-stripe-saffron { background:#FF9933; height:33.33%; }
    .flag-stripe-white   { background:#FFFFFF; height:33.33%; display:flex; align-items:center; justify-content:center; }
    .flag-stripe-green   { background:#138808; height:33.33%; }
    .flag-fade-mask {
      position:absolute;
      inset:0;
      background:linear-gradient(90deg, rgba(2,6,23,0.9) 0%, rgba(2,6,23,0) 20%, rgba(2,6,23,0) 80%, rgba(2,6,23,0.9) 100%),
                linear-gradient(180deg, rgba(2,6,23,0.7) 0%, rgba(2,6,23,0) 15%, rgba(2,6,23,0) 85%, rgba(2,6,23,0.7) 100%);
    }

    /* GST badge in single result */
    .gst-rate-badge {
      display:inline-flex;
      align-items:center;
      gap:6px;
      background:rgba(255,255,255,0.04);
      border:1px solid rgba(255,255,255,0.1);
      border-radius:10px;
      padding:0.6rem 1rem;
    }
  `;

  useEffect(() => {
    let cancelled = false;

    async function loadUser() {
      const token = authStorage.getAccessToken();
      if (!token) {
        router.replace("/login");
        return;
      }

      try {
        const user = await authApi.me();
        if (cancelled) return;
        const source = (user.full_name || user.email || "U").trim();
        setUserInitial(source.charAt(0).toUpperCase() || "U");
        setAuthReady(true);
      } catch {
        authStorage.clearTokens();
        if (!cancelled) {
          router.replace("/login");
        }
      }
    }

    loadUser();
    return () => {
      cancelled = true;
    };
  }, [router]);

  function handleLogout() {
    authStorage.clearTokens();
    router.replace("/login");
  }

  // ── Single predict ────────────────────────────────────────────────────────
  async function handlePredict(e: React.FormEvent<HTMLFormElement>) {
    e?.preventDefault();
    if (!query.trim()) return;
    setSingleError(""); setSingleLoading(true); setResult(null);
    try {
      const prediction = await hsnApi.predict(query.trim());
      setResult(prediction);
    } catch (error) {
      setSingleError(error instanceof Error ? error.message : "Prediction failed");
    } finally {
      setSingleLoading(false);
    }
  }

  // ── File processing ───────────────────────────────────────────────────────
  async function processFile(file: File) {
    setFileName(file.name);
    setFileSize((file.size / 1024).toFixed(1) + " KB");
    setBulkResults([]); setBulkError(""); setBulkStats(null); setPage(0);
    setProgress({ done: 0, total: 0 });
    setProcessSteps([false, false, false]);
    setShowFileSuccess(false);

    try {
      const lowerName = String(file.name || "").toLowerCase();
      if (lowerName.endsWith(".xls")) {
        throw new Error("Legacy .xls files are no longer supported for security reasons. Please re-save the sheet as .xlsx or .csv and upload again.");
      }

      const normalizedRows = lowerName.endsWith(".csv")
        ? await parseCsvFile(file)
        : await parseXlsxFile(file);

      if (normalizedRows.length === 0) {
        throw new Error("No data rows were found in the uploaded file.");
      }

      const columnNames = Array.from(
        new Set(
          normalizedRows.flatMap((row) =>
            Object.keys(row).filter((key) => key && !key.startsWith("__EMPTY"))
          )
        )
      );
      if (columnNames.length === 0) {
        throw new Error("The uploaded file is missing a usable header row.");
      }

      const defaultColumn = pickDefaultColumn(columnNames);
      setColumns(columnNames);
      setSelectedCol(defaultColumn);
      setRawRows(normalizedRows);
      setTimeout(() => setShowFileSuccess(true), 300);
    } catch (error) {
      setColumns([]);
      setSelectedCol("");
      setRawRows([]);
      setFileName("");
      setFileSize("");
      setBulkError(error instanceof Error ? error.message : "Unable to read the uploaded file.");
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) processFile(file);
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault(); setIsDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) processFile(file);
  }

  // ── Bulk process ──────────────────────────────────────────────────────────
  const handleBulkProcess = useCallback(async () => {
    if (rawRows.length === 0 || !selectedCol) return;
    setBulkLoading(true); setBulkError("");
    setBulkResults([]); setBulkStats(null); setPage(0);

    const steps: [boolean, boolean, boolean] = [false, false, false];
    setProcessSteps([...steps]);

    await new Promise<void>((resolve) => setTimeout(resolve, 200));
    steps[0] = true; setProcessSteps([...steps]);
    await new Promise<void>((resolve) => setTimeout(resolve, 200));
    steps[1] = true; setProcessSteps([...steps]);

    const total = rawRows.length;
    setProgress({ done: 0, total });
    const results: Array<BulkResult | undefined> = new Array(total);
    let cursor = 0;
    let completed = 0;
    const concurrency = Math.min(4, total);

    try {
      await Promise.all(
        Array.from({ length: concurrency }, async () => {
          while (true) {
            const currentIndex = cursor++;
            if (currentIndex >= total) break;

            const queryText = String(rawRows[currentIndex]?.[selectedCol] ?? "").trim();
            if (!queryText) {
              results[currentIndex] = toFailedBulkResult(`Row ${currentIndex + 1}`, "The selected column is empty for this row.");
            } else {
              try {
                results[currentIndex] = toBulkResult(queryText, await hsnApi.predict(queryText));
              } catch (error) {
                results[currentIndex] = toFailedBulkResult(queryText, error);
              }
            }

            completed += 1;
            setProgress({ done: completed, total });
            setBulkResults(results.filter((row): row is BulkResult => Boolean(row)));
          }
        })
      );

      steps[2] = true; setProcessSteps([...steps]);
      const finishedResults = results.filter((row): row is BulkResult => Boolean(row));
      const matched = finishedResults.filter((row) => row.hsn_code).length;
      const needsReview = finishedResults.filter((row) => row.needs_review || row.error).length;
      setBulkResults(finishedResults);
      setBulkStats({ matched, unmatched: needsReview, total });
      if (finishedResults.some((row) => row.error)) {
        setBulkError("Some rows could not be classified and were marked for review.");
      }
    } catch (error) {
      setBulkError(error instanceof Error ? error.message : "Bulk processing failed.");
    } finally {
      setBulkLoading(false);
    }
  }, [rawRows, selectedCol]);

  if (!authReady) {
    return (
      <div style={{ minHeight: "100vh", background: "#020617", display: "flex", alignItems: "center", justifyContent: "center", color: "#cbd5e1", fontFamily: "'Instrument Sans', sans-serif" }}>
        Loading dashboard…
      </div>
    );
  }

  function handleDownload() {
    if (bulkResults.length === 0) return;
    const rows = bulkResults.map(r => ({
      "Product Description": r.query,
      "HSN Code": padHsn(r.hsn_code),
      "Matched Description": r.description,
      "GST Rate (%)": r.gst_rate,
      "Confidence": `${Math.round(r.confidence * 100)}%`,
      "Confidence Label": r.confidence_label,
      "Review Required": r.needs_review ? "Yes" : "No",
      "Status": r.error ? r.error : "Matched",
    }));
    const csv = [
      Object.keys(rows[0]).map(escapeCsvValue).join(","),
      ...rows.map((row) => Object.values(row).map(escapeCsvValue).join(",")),
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url;
    a.download = `hsn_results_${Date.now()}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  const pageSlice = bulkResults.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages = Math.ceil(bulkResults.length / PAGE_SIZE);

  return (
    <div style={{ minHeight: "100vh", background: "#020617", color: "#e2e8f0", fontFamily: "'Instrument Sans', sans-serif", position: "relative", overflow: "hidden" }}>
      <style>{CSS}</style>

      {/* ── Deep layered background ─────────────────────────────────────── */}
      <div style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none" }}>
        <div style={{
          position: "absolute", inset: 0,
          background: `
            radial-gradient(ellipse at 20% 30%, rgba(30,58,138,0.4) 0%, transparent 55%),
            radial-gradient(ellipse at 80% 70%, rgba(37,99,235,0.2) 0%, transparent 55%),
            radial-gradient(ellipse at 50% 100%, rgba(15,23,42,0.8) 0%, transparent 70%),
            #020617`,
        }} />
        <div style={{
          position: "absolute", inset: 0, opacity: 0.035,
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
        }} />
        <div style={{
          position: "absolute", width: 600, height: 600,
          top: -200, left: -200, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(37,99,235,0.12) 0%, transparent 70%)",
          animation: "blobDrift 20s ease-in-out infinite",
        }} />
        <div style={{
          position: "absolute", width: 400, height: 400,
          bottom: -100, right: -100, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(96,165,250,0.08) 0%, transparent 70%)",
          animation: "blobDrift 26s ease-in-out infinite reverse",
        }} />
        {FLOAT_ICONS.map((ic, i) => <FloatingIcon key={i} {...ic} />)}
      </div>

      {/* ── Navbar ─────────────────────────────────────────────────────── */}
      <nav style={{
        position: "sticky", top: 0, zIndex: 100,
        height: 62,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 2rem",
        background: "rgba(2,6,23,0.85)",
        backdropFilter: "blur(24px)",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
        boxShadow: "0 1px 30px rgba(0,0,0,0.4)",
      }}>
        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
          <div style={{ width: 34, height: 34 }}>
            <LogoAnimation className="h-full w-full" />
          </div>
          <span style={{ fontFamily: "'Cabinet Grotesk', sans-serif", fontWeight: 800, fontSize: "1rem", color: "#f8fafc", letterSpacing: "-0.01em" }}>
            HSN<span style={{ color: "#3b82f6" }}>iq</span>
          </span>
        </div>

        {/* Center nav tabs */}
        <div style={{ display: "flex", gap: "0.25rem", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 12, padding: "0.25rem" }}>
          <button onClick={() => setMode("single")} className={`tab-btn ${mode === "single" ? "tab-active" : "tab-inactive"}`}>
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="7" r="4" stroke="currentColor" strokeWidth="1.5"/><path d="M2 13c0-2.2 2.7-4 6-4s6 1.8 6 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
            Single
          </button>
          <button onClick={() => setMode("bulk")} className={`tab-btn ${mode === "bulk" ? "tab-active" : "tab-inactive"}`}>
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none"><path d="M2 4h12M2 8h12M2 12h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
            Bulk Excel
          </button>
        </div>

        {/* Right */}
        <div style={{ display: "flex", alignItems: "center", gap: "1.25rem" }}>
          <div style={{ textAlign: "right" }}>
            {/* TODO: Wire usage values to an actual quota/usage API. */}
            <div style={{ fontSize: "0.65rem", color: "#475569", marginBottom: 3, fontFamily: "'DM Mono', monospace" }}>120 / 500 rows used</div>
            <div className="usage-bar" style={{ width: 80 }}><div className="usage-fill" /></div>
          </div>
          <button onClick={handleLogout} className="btn-ghost" style={{ fontSize: "0.75rem", padding: "0.55rem 0.9rem" }}>
            <LogOut size={14} />
            Logout
          </button>
          <div style={{
            width: 34, height: 34, borderRadius: "50%",
            background: "linear-gradient(135deg, #2563eb, #60a5fa)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: "0.78rem", fontWeight: 700, color: "#fff",
            boxShadow: "0 0 12px rgba(37,99,235,0.4)",
            border: "1.5px solid rgba(96,165,250,0.4)",
          }}>{userInitial}</div>
        </div>
      </nav>

      {/* ── Main ────────────────────────────────────────────────────────── */}
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "2.5rem 1.5rem", position: "relative", zIndex: 1 }}>

        {/* Page header */}
        <div style={{ marginBottom: "2rem", animation: "fadeUp 0.6s ease both" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem", position: "relative" }}>
            {/* Subtle flowing flag behind the "India · GST Classification" eyebrow */}
            <div style={{ position: "absolute", left: -20, top: -28, zIndex: 0, pointerEvents: "none" }}>
              <div className="india-flag-watermark" style={{ width: 180, height: 108 }}>
                <div className="flag-stripe-saffron" />
                <div className="flag-stripe-white">
                  <div style={{ width: 14, height: 14, borderRadius: "50%", border: "1.5px solid rgba(0,0,128,0.5)" }} />
                </div>
                <div className="flag-stripe-green" />
                <div className="flag-fade-mask" />
              </div>
            </div>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#3b82f6", boxShadow: "0 0 8px rgba(59,130,246,0.8)", position: "relative", zIndex: 1 }} />
            <span style={{ fontSize: "0.68rem", color: "#3b82f6", fontFamily: "'DM Mono', monospace", letterSpacing: "0.12em", textTransform: "uppercase", position: "relative", zIndex: 1 }}>
              India · GST Classification
            </span>
          </div>
          <h1 style={{
            fontFamily: "'Cabinet Grotesk', sans-serif",
            fontSize: "1.85rem", fontWeight: 800,
            color: "#f8fafc", margin: 0,
            letterSpacing: "-0.025em",
          }}>
            HSN Code Lookup
          </h1>
          <p style={{ fontSize: "0.82rem", color: "#475569", marginTop: 6 }}>
            AI-powered classification for Indian GST compliance
          </p>
        </div>

        {/* ════════════════════ SINGLE MODE ════════════════════ */}
        {mode === "single" && (
          <div style={{ animation: "fadeUp 0.5s ease both" }}>
            {/* Search bar */}
            <form onSubmit={handlePredict} style={{ display: "flex", gap: "0.625rem", marginBottom: "1.5rem" }}>
              <div style={{ flex: 1, position: "relative" }}>
                <svg style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", opacity: 0.35 }}
                  width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <circle cx="6.5" cy="6.5" r="4.5" stroke="#94a3b8" strokeWidth="1.5"/>
                  <path d="M10 10l4 4" stroke="#94a3b8" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
                <input
                  value={query}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQuery(e.target.value)}
                  placeholder="Type a product description e.g. Colgate Toothpaste 200g..."
                  className="input-field"
                  style={{ paddingLeft: "2.5rem" }}
                />
              </div>
              <button type="submit" disabled={singleLoading || !query.trim()} className="btn-primary">
                {singleLoading ? (
                  <div className="loading-dots"><span/><span/><span/></div>
                ) : (
                  <>
                    <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                      <path d="M7 2l7 6-7 6" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    Classify
                  </>
                )}
              </button>
            </form>

            {/* Example chips */}
            {!result && !singleLoading && (
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "2rem" }}>
                {["Colgate Toothpaste 200g", "Horlicks Womens 400g", "VKC Chappal 7", "Basmati Rice 5kg"].map(ex => (
                  <button key={ex} onClick={() => { setQuery(ex); }} style={{
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    color: "#64748b",
                    padding: "0.35rem 0.9rem",
                    borderRadius: 100,
                    fontSize: "0.73rem",
                    fontFamily: "'DM Mono', monospace",
                    cursor: "pointer",
                    transition: "all 0.2s",
                  }}
                  onMouseEnter={(e: React.MouseEvent<HTMLButtonElement>) => {
                    e.currentTarget.style.color = "#93c5fd";
                    e.currentTarget.style.borderColor = "rgba(96,165,250,0.3)";
                  }}
                  onMouseLeave={(e: React.MouseEvent<HTMLButtonElement>) => {
                    e.currentTarget.style.color = "#64748b";
                    e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
                  }}>
                    {ex}
                  </button>
                ))}
              </div>
            )}

            {singleError && (
              <div style={{
                display: "flex", alignItems: "center", gap: "0.5rem",
                background: "rgba(248,113,113,0.08)",
                border: "1px solid rgba(248,113,113,0.2)",
                color: "#fca5a5", fontSize: "0.8rem",
                padding: "0.75rem 1rem", borderRadius: 12, marginBottom: "1rem",
              }}>
                ⚠ {singleError}
              </div>
            )}

            {result && (
              <div style={{ animation: "fadeUp 0.4s ease both" }}>
                {/* Big HSN result card */}
                <div className="glass-card-bright" style={{ padding: "3rem 2rem", textAlign: "center", marginBottom: "0.875rem", position: "relative", overflow: "hidden" }}>
                  <div style={{
                    position: "absolute", inset: 0,
                    background: "radial-gradient(ellipse at center, rgba(37,99,235,0.06) 0%, transparent 70%)",
                    pointerEvents: "none",
                  }} />
                  <div className="lbl">Classified HSN Code</div>
                  <div className="hsn-big">{padHsn(result.top_match.hsn_code)}</div>
                  <div style={{ fontSize: "0.85rem", color: "#64748b", marginTop: "0.75rem", maxWidth: 400, margin: "0.75rem auto 0" }}>
                    {result.top_match.full_description ?? result.top_match.description}
                  </div>

                  {/* Pills row: confidence + GST rate */}
                  <div style={{ marginTop: "1.25rem", display: "flex", justifyContent: "center", gap: "0.6rem", flexWrap: "wrap", alignItems: "center" }}>
                    <ConfPill label={result.confidence_label} value={result.confidence} />
                    <GstPill rate={result.gst_rate ?? result.top_match.gst_rate} />
                    <span style={{ fontSize: "0.7rem", color: "#334155", fontFamily: "'DM Mono', monospace" }}>
                      via {result.top_match.method}
                    </span>
                  </div>

                  {/* GST detail bar */}
                  {(result.gst_rate != null || result.top_match.gst_rate != null) && (
                    <div style={{
                      marginTop: "1.5rem",
                      display: "inline-flex",
                      gap: "1.5rem",
                      background: "rgba(0,0,0,0.2)",
                      border: "1px solid rgba(255,255,255,0.06)",
                      borderRadius: 12,
                      padding: "0.75rem 1.5rem",
                    }}>
                      <div style={{ textAlign: "center" }}>
                        <div style={{ fontSize: "0.6rem", color: "#334155", textTransform: "uppercase", letterSpacing: "0.1em", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>GST Rate</div>
                        <div style={{ fontFamily: "'Cabinet Grotesk', sans-serif", fontWeight: 800, fontSize: "1.4rem", color: "#4ade80", lineHeight: 1 }}>
                          {result.gst_rate ?? result.top_match.gst_rate}%
                        </div>
                      </div>
                      <div style={{ width: 1, background: "rgba(255,255,255,0.06)", alignSelf: "stretch" }} />
                      <div style={{ textAlign: "center" }}>
                        <div style={{ fontSize: "0.6rem", color: "#334155", textTransform: "uppercase", letterSpacing: "0.1em", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>HSN Chapter</div>
                        <div style={{ fontFamily: "'DM Mono', monospace", fontWeight: 500, fontSize: "1.2rem", color: "#60a5fa", lineHeight: 1 }}>
                          {result.top_match.chapter ?? padHsn(result.top_match.hsn_code).slice(0, 2)}
                        </div>
                      </div>
                      <div style={{ width: 1, background: "rgba(255,255,255,0.06)", alignSelf: "stretch" }} />
                      <div style={{ textAlign: "center" }}>
                        <div style={{ fontSize: "0.6rem", color: "#334155", textTransform: "uppercase", letterSpacing: "0.1em", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>Review</div>
                        <div style={{ fontSize: "0.8rem", color: result.needs_review ? "#f87171" : "#4ade80", fontWeight: 600 }}>
                          {result.needs_review ? "Needed" : "Clear"}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Alternatives */}
                {result.alternatives.length > 0 && (
                  <div className="glass-card" style={{ overflow: "hidden" }}>
                    <div style={{ padding: "1rem 1.25rem 0.5rem" }}>
                      <div className="lbl">Alternative Matches</div>
                    </div>
                    <table className="data-table">
                      <thead><tr>
                        <th>HSN Code</th><th>Description</th><th>GST%</th><th>Confidence</th>
                      </tr></thead>
                      <tbody>
                        {result.alternatives.map(a => (
                          <tr key={a.hsn_code}>
                            <td><span className="hsn-sm">{padHsn(a.hsn_code)}</span></td>
                            <td style={{ maxWidth: 280 }}>
                              <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "0.78rem", color: "#475569" }}>{a.full_description ?? a.description}</span>
                            </td>
                            <td>
                              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.75rem", color: "#4ade80", fontWeight: 600 }}>
                                {a.gst_rate != null ? `${a.gst_rate}%` : "—"}
                              </span>
                            </td>
                            <td><ConfPill label={a.score >= 0.8 ? "high" : a.score >= 0.55 ? "medium" : "low"} value={a.score} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {!result && !singleLoading && (
              <div style={{ textAlign: "center", padding: "5rem 2rem" }}>
                <div style={{ display: "inline-flex", flexDirection: "column", gap: "0.75rem", marginBottom: "2rem" }}>
                  {[
                    { prod: "Horlicks Womens 400g", hsn: "21069099", conf: 0.91, gst: 18 },
                    { prod: "VKC Chappal Size 7",   hsn: "64021000", conf: 0.97, gst: 5  },
                    { prod: "Aashirvaad Atta 5kg",  hsn: "11010000", conf: 0.95, gst: 5  },
                  ].map((item, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontSize: "0.72rem", color: "#475569", fontFamily: "'DM Mono', monospace" }}>{item.prod}</span>
                      <span style={{ color: "#334155", fontSize: "0.7rem" }}>→</span>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.72rem", color: "#3b82f6" }}>{item.hsn}</span>
                      <ConfPill label="high" value={item.conf} />
                      <GstPill rate={item.gst} />
                    </div>
                  ))}
                </div>
                <p style={{ fontSize: "0.8rem", color: "#334155" }}>Type any product description above</p>
              </div>
            )}
          </div>
        )}

        {/* ════════════════════ BULK MODE ════════════════════ */}
        {mode === "bulk" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem", animation: "fadeUp 0.5s ease both" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
              {/* Upload zone */}
              <div className="glass-card" style={{ padding: "1.5rem" }}>
                <div className="lbl">Step 1 — Upload Excel / CSV</div>
                <div
                  className={`upload-zone${isDragOver ? " drag" : ""}`}
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={(e: React.DragEvent<HTMLDivElement>) => { e.preventDefault(); setIsDragOver(true); }}
                  onDragLeave={() => setIsDragOver(false)}
                  onDrop={handleDrop}
                >
                  <div className="corner c-tl" /><div className="corner c-tr" />
                  <div className="corner c-bl" /><div className="corner c-br" />

                  {showFileSuccess ? (
                    <div style={{ animation: "fadeUp 0.4s ease" }}>
                      <div style={{
                        width: 52, height: 52, borderRadius: "50%",
                        background: "rgba(34,197,94,0.15)",
                        border: "1.5px solid rgba(34,197,94,0.4)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        margin: "0 auto 1rem",
                        animation: "checkPop 0.4s ease",
                      }}>
                        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                          <polyline points="4,10 8,14 16,6" stroke="#4ade80" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      </div>
                      <p style={{ fontSize: "0.85rem", color: "#f8fafc", margin: "0 0 4px", fontWeight: 600 }}>{fileName}</p>
                      <p style={{ fontSize: "0.72rem", color: "#64748b", margin: 0, fontFamily: "'DM Mono', monospace" }}>
                        {fileSize} · {rawRows.length} rows detected
                      </p>
                    </div>
                  ) : (
                    <>
                      <div className="upload-icon-ring">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                          <path d="M12 3v12M8 7l4-4 4 4" stroke="#60a5fa" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                          <path d="M3 17v2a2 2 0 002 2h14a2 2 0 002-2v-2" stroke="#60a5fa" strokeWidth="1.8" strokeLinecap="round"/>
                        </svg>
                      </div>
                      <p style={{ fontSize: "0.88rem", color: "#94a3b8", margin: "0 0 0.4rem", fontWeight: 500 }}>
                        Drop your Excel here or <span style={{ color: "#60a5fa" }}>browse files</span>
                      </p>
                      <p style={{ fontSize: "0.7rem", color: "#334155", margin: 0, fontFamily: "'DM Mono', monospace" }}>
                        XLSX · CSV · up to 500 rows
                      </p>
                    </>
                  )}
                  <input ref={fileInputRef} type="file" accept=".xlsx,.csv" style={{ display: "none" }} onChange={handleFileChange} />
                </div>
              </div>

              {/* Config + process panel */}
              <div className="glass-card" style={{ padding: "1.5rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div>
                  <div className="lbl">Step 2 — Select column</div>
                  <select
                    value={selectedCol}
                    onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setSelectedCol(e.target.value)}
                    className="select-field"
                    style={{ width: "100%" }}
                  >
                    {columns.length === 0 && <option value="">Upload a file first</option>}
                    {columns.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                  {selectedCol && rawRows.slice(0,2).map((r,i) => (
                    <div key={i} style={{
                      fontSize: "0.7rem", color: "#475569",
                      background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.04)",
                      borderRadius: 6, padding: "4px 8px", marginTop: 4,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      fontFamily: "'DM Mono', monospace",
                    }}>
                      {String(r[selectedCol] || "").slice(0,60) || "—"}
                    </div>
                  ))}
                </div>

                {(bulkLoading || processSteps.some(Boolean)) ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "1rem", background: "rgba(0,0,0,0.2)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.05)" }}>
                    <ProcessStep label="Analyzing products..." done={processSteps[0]} active={bulkLoading && !processSteps[0]} />
                    <ProcessStep label="Cleaning & normalizing data" done={processSteps[1]} active={bulkLoading && processSteps[0] && !processSteps[1]} />
                    <ProcessStep label="Mapping HSN codes" done={processSteps[2]} active={bulkLoading && processSteps[1] && !processSteps[2]} />
                  </div>
                ) : null}

                {bulkLoading && progress.total > 0 && (
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ fontSize: "0.7rem", color: "#475569", fontFamily: "'DM Mono', monospace" }}>Processing...</span>
                      <span style={{ fontSize: "0.7rem", color: "#60a5fa", fontFamily: "'DM Mono', monospace" }}>{progress.done}/{progress.total}</span>
                    </div>
                    <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 4, overflow: "hidden" }}>
                      <div style={{
                        height: "100%",
                        background: "linear-gradient(90deg, #2563eb, #60a5fa)",
                        borderRadius: 4,
                        width: `${(progress.done/progress.total)*100}%`,
                        transition: "width 0.15s linear",
                        boxShadow: "0 0 10px rgba(96,165,250,0.5)",
                      }} />
                    </div>
                  </div>
                )}

                <div style={{ marginTop: "auto" }}>
                  <button
                    onClick={handleBulkProcess}
                    disabled={bulkLoading || columns.length === 0 || !selectedCol}
                    className="btn-primary"
                    style={{ width: "100%", justifyContent: "center", padding: "0.8rem" }}
                  >
                    {bulkLoading ? (
                      <div className="loading-dots"><span/><span/><span/></div>
                    ) : (
                      <>
                        <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                          <path d="M8 2L14 8L8 14" stroke="white" strokeWidth="2" strokeLinecap="round"/>
                          <path d="M2 8h12" stroke="white" strokeWidth="2" strokeLinecap="round"/>
                        </svg>
                        Process {rawRows.length > 0 ? rawRows.length.toLocaleString() : ""} rows
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>

            {bulkError && (
              <div style={{ background: "rgba(248,113,113,0.08)", border: "1px solid rgba(248,113,113,0.2)", color: "#fca5a5", fontSize: "0.8rem", padding: "0.75rem 1rem", borderRadius: 12 }}>
                ⚠ {bulkError}
              </div>
            )}

            {/* Stats */}
            {bulkStats && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.875rem" }}>
                {[
                  { label: "Total Rows", val: bulkStats.total, color: "#e2e8f0", icon: "📋" },
                  { label: "Matched", val: bulkStats.matched, color: "#4ade80", icon: "✓" },
                  { label: "Needs Review", val: bulkStats.unmatched, color: "#fb923c", icon: "⚠" },
                ].map(s => (
                  <div key={s.label} className="stat-card">
                    <div style={{ fontSize: "1.2rem", marginBottom: "0.4rem", opacity: 0.7 }}>{s.icon}</div>
                    <div style={{ fontFamily: "'Cabinet Grotesk', sans-serif", fontSize: "2rem", fontWeight: 800, color: s.color, lineHeight: 1 }}>
                      {s.val.toLocaleString()}
                    </div>
                    <div style={{ fontSize: "0.68rem", color: "#334155", textTransform: "uppercase", letterSpacing: "0.08em", marginTop: 4 }}>
                      {s.label}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Results table */}
            {bulkResults.length > 0 && (
              <div className="glass-card" style={{ overflow: "hidden" }}>
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "1rem 1.25rem",
                  borderBottom: "1px solid rgba(255,255,255,0.05)",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                    <span style={{ fontFamily: "'Cabinet Grotesk', sans-serif", fontWeight: 700, fontSize: "0.9rem", color: "#f8fafc" }}>Results</span>
                    {bulkLoading && <div className="loading-dots" style={{ display: "inline-flex" }}><span/><span/><span/></div>}
                  </div>
                  <button onClick={handleDownload} disabled={bulkLoading} className="btn-ghost" style={{ fontSize: "0.75rem" }}>
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                      <path d="M8 2v9M4 8l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                      <path d="M2 14h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                    </svg>
                    Download CSV
                  </button>
                </div>

                <div style={{ overflowX: "auto" }}>
                  <table className="data-table">
                    <thead><tr>
                      <th style={{ width: 40 }}>#</th>
                      <th>Description</th>
                      <th>HSN Code</th>
                      <th>GST%</th>
                      <th>Confidence</th>
                    </tr></thead>
                    <tbody>
                      {pageSlice.map((r, i) => {
                        const rowNum = page * PAGE_SIZE + i + 1;
                        return (
                          <tr key={rowNum}>
                            <td style={{ color: "#1e293b", fontFamily: "'DM Mono', monospace", fontSize: "0.7rem" }}>{rowNum}</td>
                            <td style={{ maxWidth: 280 }}>
                              <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "0.78rem", color: "#64748b" }}>{r.query}</span>
                            </td>
                            <td><span className="hsn-sm">{padHsn(r.hsn_code)}</span></td>
                            <td style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.75rem", color: "#4ade80", fontWeight: 600 }}>
                              {r.gst_rate != null ? `${r.gst_rate}%` : "—"}
                            </td>
                            <td><ConfPill label={r.confidence_label} value={r.confidence} /></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {totalPages > 1 && (
                  <div style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "0.875rem 1.25rem",
                    borderTop: "1px solid rgba(255,255,255,0.05)",
                  }}>
                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.7rem", color: "#334155" }}>
                      {page * PAGE_SIZE + 1}–{Math.min((page+1)*PAGE_SIZE, bulkResults.length)} of {bulkResults.length.toLocaleString()}
                    </span>
                    <div style={{ display: "flex", gap: "0.35rem" }}>
                      <button onClick={() => setPage(Math.max(0,page-1))} disabled={page===0} className="btn-ghost" style={{ padding: "0.35rem 0.6rem" }}>←</button>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.7rem", color: "#475569", padding: "0 0.35rem", display: "flex", alignItems: "center" }}>{page+1}/{totalPages}</span>
                      <button onClick={() => setPage(Math.min(totalPages-1,page+1))} disabled={page>=totalPages-1} className="btn-ghost" style={{ padding: "0.35rem 0.6rem" }}>→</button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {bulkResults.length === 0 && !bulkLoading && columns.length === 0 && (
              <div style={{ textAlign: "center", padding: "4rem 2rem" }}>
                <p style={{ fontSize: "0.8rem", color: "#334155", marginBottom: 4 }}>Upload a spreadsheet to begin</p>
                <p style={{ fontSize: "0.72rem", color: "#1e293b" }}>Supports .xlsx and .csv</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      <footer style={{
        borderTop: "1px solid rgba(255,255,255,0.04)",
        padding: "1rem 1.5rem",
        marginTop: "2rem",
        position: "relative", zIndex: 1,
      }}>
        <div style={{ maxWidth: 1080, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: "0.68rem", color: "#1e293b", fontFamily: "'DM Mono', monospace" }}>
            HSNiq · AI-powered GST classification for India
          </span>
          <span style={{ fontSize: "0.68rem", color: "#334155" }}>
            Built by <span style={{ color: "#3b82f6" }}>DhanushRaghav</span>
          </span>
        </div>
      </footer>
    </div>
  );
}
