#!/usr/bin/env python3
"""Score classify pipeline against the client Excel product catalog."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_DEFAULT_EXCEL = Path(r"c:\Users\Admin\Pictures\sample.xlsx")
if not _DEFAULT_EXCEL.exists():
    _DEFAULT_EXCEL = ROOT / "data" / "client_sample.xlsx"

_INVALID_HSN = frozenset({"", "UNKNOWN", "UNCLASSIFIED", "99999999", None})

_TIER_BUCKETS = (
    ("L0 verified_products", ("L0_verified_product",)),
    ("L0 Kerala retail", ("L0_kerala_retail", "kerala_alias", "kerala_")),
    ("L0 alias_dict", ("L0_alias_dict", "in_memory_alias")),
    ("L1 brand_aliases", ("brand_alias", "L1_brand_alias")),
    ("language_aliases", ("language_alias", "alias_expand")),
    ("L3 curated_master", ("L3_curated_master", "curated_master")),
    ("L4 tariff_fallback", ("L4_tariff_fallback", "L4_keyword", "tariff")),
    ("L5 broad_resolution", ("L5_fuzzy", "L5_broad", "multi_layer", "inverted", "trigram")),
    ("L5 keyword_fallback", ("L5_keyword_fallback", "keyword_hsn_search")),
    ("UNCLASSIFIED", ("L6_pending_review", "pending_review", "UNCLASSIFIED")),
)

_MALAYALAM_RE = __import__("re").compile(r"[\u0D00-\u0D7F]")
_KERALA_ROMAN_HINTS = frozenset({
    "MANJAL", "CHERUPAYAR", "CHEMMEEN", "PUJA", "SAMBAR", "RASAM", "PUTTU", "AVAL",
    "MATTA", "KAPPA", "CHAKKA", "VAZHAKKA", "KARIMEEN", "VELLAM", "CHAYA", "VELICHENNA",
    "MULAKU", "KAAYAM", "PUZHUKKALARI", "THUVARA", "KADALA", "NENDRAN", "UZHUNNU",
})


def _load_env_neon() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _load_names(path: Path) -> list[str]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    out: list[str] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        if row and row[0]:
            text = str(row[0]).strip()
            if text:
                out.append(text)
    wb.close()
    return out


def _is_detected(result: dict) -> bool:
    hsn = (result.get("hsn_code") or "").strip()
    if not hsn or hsn in _INVALID_HSN:
        return False
    digits = "".join(c for c in hsn if c.isdigit())
    if len(digits) not in (4, 6, 8):
        return False
    if result.get("gst_rate") is None:
        return False
    conf = int(result.get("confidence_score") or result.get("confidence") or 0)
    if conf < 70:
        return False
    if result.get("needs_manual_review") or result.get("review_required"):
        return False
    return True


def _is_kerala_style(description: str) -> bool:
    if _MALAYALAM_RE.search(description or ""):
        return True
    upper = (description or "").upper()
    return any(h in upper for h in _KERALA_ROMAN_HINTS)


def _kerala_layer_bucket(layer: str | None) -> str:
    layer_l = (layer or "").lower()
    if "l0_kerala" in layer_l or layer_l.startswith("kerala_"):
        return "L0_kerala_retail"
    if "language_alias" in layer_l or "alias_expand" in layer_l:
        return "language_aliases"
    if "l5" in layer_l or "fuzzy" in layer_l or "multi_layer" in layer_l:
        return "L5_broad_resolution"
    if "l6" in layer_l or "pending" in layer_l or "unclassified" in layer_l:
        return "L6_pending_review"
    if layer_l.startswith("l0") or "verified" in layer_l:
        return "L0_exact_other"
    return "other"


def _print_kerala_summary(rows: list[dict]) -> None:
    kerala_rows = [r for r in rows if _is_kerala_style(r.get("description", ""))]
    if not kerala_rows:
        print("\n(No Kerala-style rows detected in this sample.)")
        return

    exact = authoritative = pending = 0
    layer_counts: Counter[str] = Counter()
    unresolved: Counter[str] = Counter()

    for r in kerala_rows:
        layer_counts[_kerala_layer_bucket(r.get("layer_matched"))] += 1
        if r.get("detected"):
            conf = int(r.get("confidence") or 0)
            if conf >= 95:
                exact += 1
            elif conf >= 70:
                authoritative += 1
        elif _kerala_layer_bucket(r.get("layer_matched")) == "L6_pending_review":
            pending += 1
            unresolved[r.get("description", "")[:60]] += 1

    total = len(kerala_rows)
    print("\n┌─────────────────────────────────────────────────────────────┐")
    print("│           KERALA / MALAYALAM HIT-RATE SUMMARY               │")
    print("├─────────────────────────────────────────────────────────────┤")
    print(f"│ Kerala-style rows in sample     │ {total:8d}              │")
    print(f"│ Exact-tier hits (conf ≥95)        │ {exact:8d} ({100*exact/total:5.1f}%) │")
    print(f"│ Authoritative (conf ≥70)        │ {authoritative:8d} ({100*authoritative/total:5.1f}%) │")
    print(f"│ Pending / L6 review             │ {pending:8d} ({100*pending/total:5.1f}%) │")
    print("├─────────────────────────────────────────────────────────────┤")
    for label in ("L0_kerala_retail", "language_aliases", "L5_broad_resolution", "L6_pending_review", "other"):
        n = layer_counts.get(label, 0)
        if n:
            print(f"│ {label:<30} │ {n:8d}              │")
    print("└─────────────────────────────────────────────────────────────┘")
    if unresolved:
        print("\nTop unresolved Malayalam/Kerala terms:")
        for term, cnt in unresolved.most_common(15):
            print(f"  {cnt}x  {term}")


def _compare_reports(before_path: Path, after_path: Path) -> None:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    print("\n=== Before / After comparison ===")
    print(
        f"Detection: {before.get('detection_score_pct')}% -> {after.get('detection_score_pct')}% "
        f"({before.get('detected')}/{before.get('total_products')} -> "
        f"{after.get('detected')}/{after.get('total_products')})"
    )


def _tier_bucket(layer: str | None) -> str:
    layer_l = (layer or "").lower()
    for label, keys in _TIER_BUCKETS:
        if any(k.lower() in layer_l for k in keys):
            return label
    return "UNCLASSIFIED"


def _print_tier_table(rows: list[dict], total: int) -> None:
    bucket_conf: dict[str, list[int]] = defaultdict(list)
    bucket_count: Counter[str] = Counter()
    for r in rows:
        if not r.get("detected"):
            bucket_count["UNCLASSIFIED"] += 1
            continue
        b = _tier_bucket(r.get("layer_matched"))
        bucket_count[b] += 1
        if r.get("confidence") is not None:
            bucket_conf[b].append(int(r["confidence"]))

    print("\n┌─────────────────────────────────────────────────────────────┐")
    print("│              DETECTION BREAKDOWN BY TIER                    │")
    print("├────────────────────────┬──────────┬──────────┬─────────────┤")
    print("│ Tier                   │ Detected │ % Total  │ Confidence  │")
    print("├────────────────────────┼──────────┼──────────┼─────────────┤")
    detected_total = 0
    for label, _ in _TIER_BUCKETS:
        n = bucket_count.get(label, 0)
        if label == "UNCLASSIFIED":
            continue
        detected_total += n
        pct = 100.0 * n / total if total else 0
        confs = bucket_conf.get(label, [])
        avg = f"avg: {sum(confs)/len(confs):.0f}" if confs else "-"
        print(f"│ {label:<22} │ {n:8d} │ {pct:6.1f}% │ {avg:11} │")
    uncl = bucket_count.get("UNCLASSIFIED", 0)
    print(f"│ {'UNCLASSIFIED':<22} │ {uncl:8d} │ {100*uncl/total if total else 0:6.1f}% │ {'-':11} │")
    print("├────────────────────────┼──────────┼──────────┼─────────────┤")
    print(f"│ {'TOTAL DETECTED':<22} │ {detected_total:8d} │ {100*detected_total/total if total else 0:6.1f}% │             │")
    print("└────────────────────────┴──────────┴──────────┴─────────────┘")


async def _run_classify(
    names: list[str],
    concurrency: int,
    skip_faiss: bool,
    *,
    skip_faiss_cli: bool = False,
) -> list[dict]:
    os.environ.setdefault("SECRET_KEY", "excel-test-secret-key-32chars-min")
    os.environ.setdefault("API_KEY", "dev-api-key")
    os.environ.setdefault("ADMIN_API_KEY", "dev-admin-key")

    if skip_faiss:
        os.environ["FAISS_DISABLED"] = "1"
        if skip_faiss_cli:
            print(
                "FAISS tier-5 skipped (--skip-faiss). "
                "L3/L4/L5 pg_trgm layers will still run."
            )
        else:
            print(
                "FAISS tier-5 skipped (SQLite bulk mode). "
                "L3/L4/L5 pg_trgm layers will still run."
            )
    else:
        try:
            from app.services.matcher import get_matcher

            get_matcher()
            print("Matcher warmed (single FAISS load)")
        except Exception as exc:
            print(f"Matcher warm-up skipped: {exc}")

    from app.models.database import async_session, init_db
    from app.services.gst_classifier import classify

    await init_db()
    sem = asyncio.Semaphore(concurrency)
    rows: list[dict] = []
    done = 0
    total = len(names)
    lock = asyncio.Lock()

    pbar = None
    try:
        from tqdm import tqdm
        pbar = tqdm(total=total, desc="Classifying", unit="product")
    except ImportError:
        pass

    async def _one(desc: str) -> None:
        nonlocal done
        async with sem:
            t0 = time.perf_counter()
            async with async_session() as db:
                out = await classify(db, desc, bypass_cache=True)
            row = {
                "description": desc,
                "detected": _is_detected(out),
                "hsn_code": out.get("hsn_code"),
                "gst_rate": out.get("gst_rate"),
                "confidence": out.get("confidence"),
                "layer_matched": out.get("matched_layer") or out.get("source"),
                "tier_used": out.get("tier_used"),
                "failure_reason": None if _is_detected(out) else "no_match_all_layers",
                "time_ms": round((time.perf_counter() - t0) * 1000, 2),
            }
            async with lock:
                rows.append(row)
                done += 1
                if pbar is not None:
                    pbar.update(1)
                elif done % 500 == 0 or done == total:
                    print(f"  classified {done}/{total}...")

    await asyncio.gather(*[_one(n) for n in names])
    if pbar is not None:
        pbar.close()
    return rows


async def _print_preflight_warnings(database_url: str, require_kerala: bool) -> dict:
    from datetime import datetime, timezone

    from app.models.database import async_session, init_db
    from app.services.benchmark_preflight import (
        collect_benchmark_metadata,
        enforce_kerala_corpus_preflight,
    )

    await init_db()
    async with async_session() as db:
        meta = await collect_benchmark_metadata(db, database_url)
    meta["benchmark_started_utc"] = datetime.now(timezone.utc).isoformat()

    for warning in meta.get("warnings") or []:
        print(f"\n*** BENCHMARK WARNING: {warning}")

    if meta.get("dialect") == "postgresql" and not meta.get("kerala_corpus_seeded"):
        print(
            "\n*** 'After' metrics may be misleading until you run:\n"
            "    python scripts/seed_kerala_language_aliases.py\n"
        )

    enforce_kerala_corpus_preflight(meta, require=require_kerala)
    return meta


async def main_async(args: argparse.Namespace) -> int:
    if args.neon:
        _load_env_neon()

    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./hsn_dev.db")
    is_postgres = "postgresql" in database_url
    skip_faiss = not is_postgres

    benchmark_meta = await _print_preflight_warnings(
        database_url, require_kerala=args.require_kerala_corpus,
    )

    if args.neon and is_postgres:
        skip_faiss = False
        print("Running against Neon Postgres with full pipeline (trgm + fts + FAISS + keyword fallback)")

    if args.skip_faiss:
        skip_faiss = True

    names = _load_names(args.excel)
    if args.sample:
        random.seed(42)
        names = random.sample(names, min(args.sample, len(names)))
        print(f"Testing on sample of {len(names)} rows")
    elif args.limit:
        names = names[: args.limit]

    print(f"Testing {len(names)} products from {args.excel}")

    rows = await _run_classify(
        names,
        args.concurrency,
        skip_faiss=skip_faiss,
        skip_faiss_cli=args.skip_faiss,
    )
    detected = [r for r in rows if r["detected"]]
    missed = [r for r in rows if not r["detected"]]
    missed.sort(key=lambda r: r["description"].upper())

    score_pct = round(100.0 * len(detected) / len(rows), 2) if rows else 0.0
    if not args.quick:
        print(f"\nDetection score: {score_pct}% ({len(detected)}/{len(rows)})")
    _print_tier_table(rows, len(rows))
    _print_kerala_summary(rows)

    kerala_rows = [r for r in rows if _is_kerala_style(r.get("description", ""))]
    kerala_detected = [r for r in kerala_rows if r.get("detected")]
    kerala_exact_alias = [
        r for r in kerala_detected
        if _kerala_layer_bucket(r.get("layer_matched"))
        in ("L0_kerala_retail", "language_aliases")
    ]

    report = {
        "excel": str(args.excel),
        "database": "neon" if is_postgres else "sqlite",
        "benchmark_metadata": benchmark_meta,
        "total_products": len(rows),
        "detected": len(detected),
        "undetected": len(missed),
        "detection_score_pct": score_pct,
        "undetected_products": missed,
        "detected_products": detected,
        "kerala_style_total": len(kerala_rows),
        "kerala_detected": len(kerala_detected),
        "kerala_exact_or_alias_hits": len(kerala_exact_alias),
        "kerala_hit_rate_pct": round(
            100.0 * len(kerala_detected) / len(kerala_rows), 2,
        ) if kerala_rows else None,
    }
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if not args.quick:
        print(f"Report: {args.output}")
    if args.compare_before and args.compare_before.exists():
        _compare_reports(args.compare_before, args.output)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", type=Path, default=_DEFAULT_EXCEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Shorter run: default sample=200 and suppress verbose summary",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full catalog (overrides --quick default sample)",
    )
    parser.add_argument("--neon", action="store_true")
    parser.add_argument(
        "--compare-before",
        type=Path,
        default=None,
        help="Previous client_excel_report.json for before/after metrics",
    )
    parser.add_argument(
        "--skip-faiss",
        action="store_true",
        help="Skip FAISS tier-5 warm-up (faster run to test L3/L4/L5 only)",
    )
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument(
        "--require-kerala-corpus",
        action="store_true",
        help="Exit if Postgres Kerala corpus (language_aliases) is not seeded",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "scripts" / "client_excel_report.json")
    args = parser.parse_args()
    if args.quick and not args.sample and not args.full:
        args.sample = 200
    if not args.excel.exists():
        sys.exit(f"Excel not found: {args.excel}")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
