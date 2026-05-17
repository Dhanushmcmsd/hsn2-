#!/usr/bin/env python3
"""Score classify + search pipeline against the client Excel product catalog."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_DEFAULT_EXCEL = Path(r"c:\Users\Admin\Pictures\sample.xlsx")
if not _DEFAULT_EXCEL.exists():
    _DEFAULT_EXCEL = ROOT / "data" / "client_sample.xlsx"

_INVALID_HSN = frozenset({"", "UNKNOWN", "UNCLASSIFIED", "99999999", None})


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


def _failure_reason(result: dict) -> str:
    hsn = (result.get("hsn_code") or "").strip()
    if not hsn or hsn in _INVALID_HSN:
        return "no_match_all_layers"
    if result.get("gst_rate") is None:
        return "hsn_without_gst"
    conf = int(result.get("confidence") or 0)
    if conf < 70:
        return "low_confidence_fuzzy"
    if result.get("needs_manual_review") or result.get("review_required"):
        return "queued_manual_review"
    return "unknown"


async def _run_classify(names: list[str], concurrency: int) -> list[dict]:
    import app.services.gst_classifier as gst_mod
    from app.models.database import async_session, init_db
    from app.services.gst_classifier import classify

    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./hsn_dev.db")
    os.environ.setdefault("SECRET_KEY", "excel-test-secret-key-32chars-min")
    os.environ.setdefault("API_KEY", "dev-api-key")
    os.environ.setdefault("ADMIN_API_KEY", "dev-admin-key")

    # Bulk Excel eval: skip FAISS tier-5 (Neon CI / single-query API still uses full stack).
    async def _skip_tier5_multi(_db, _query: str):
        return None

    gst_mod._tier5_multi_layer = _skip_tier5_multi
    print("Note: tier-5 FAISS skipped for bulk Excel scoring (see Neon CI for full stack)")

    await init_db()
    sem = asyncio.Semaphore(concurrency)
    rows: list[dict] = []

    done = 0
    total = len(names)
    lock = asyncio.Lock()

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
                "failure_reason": None if _is_detected(out) else _failure_reason(out),
                "time_ms": round((time.perf_counter() - t0) * 1000, 2),
            }
            async with lock:
                rows.append(row)
                done += 1
                if done % 500 == 0 or done == total:
                    print(f"  classified {done}/{total}...")

    await asyncio.gather(*[_one(n) for n in names])
    return rows


async def _run_search_sample(names: list[str], sample_size: int) -> dict:
    """Spot-check /search/products (multi_layer) on a sample."""
    from app.models.database import async_session, init_db
    from app.services.search_service import search_products

    await init_db()
    sample = names[:sample_size]
    ok = 0
    async with async_session() as db:
        for q in sample:
            try:
                resp = await search_products(db, q, top_k=1)
                if resp.results and resp.results[0].hsn_code:
                    ok += 1
            except Exception:
                pass
    return {"sample_size": len(sample), "with_results": ok}


async def main_async(args: argparse.Namespace) -> int:
    names = _load_names(args.excel)
    if args.limit:
        names = names[: args.limit]
    print(f"Testing {len(names)} products from {args.excel}")

    rows = await _run_classify(names, args.concurrency)
    detected = [r for r in rows if r["detected"]]
    missed = [r for r in rows if not r["detected"]]
    missed.sort(key=lambda r: r["description"].upper())

    layer_counts = Counter(r["layer_matched"] for r in detected)
    reason_counts = Counter(r["failure_reason"] for r in missed)

    search_check = {}
    if args.check_search:
        search_check = await _run_search_sample(names, min(50, len(names)))

    score_pct = round(100.0 * len(detected) / len(rows), 2) if rows else 0.0
    report = {
        "excel": str(args.excel),
        "total_products": len(rows),
        "detected": len(detected),
        "undetected": len(missed),
        "detection_score_pct": score_pct,
        "layers_used_on_detected": dict(layer_counts),
        "undetected_by_reason": dict(reason_counts),
        "search_spot_check": search_check,
        "undetected_products": missed,
        "detected_products": detected,
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nDetection score: {score_pct}% ({len(detected)}/{len(rows)})")
    print("Layers (detected):", dict(layer_counts))
    print("Failure reasons:", dict(reason_counts))
    if search_check:
        print("Search spot-check:", search_check)
    print(f"Report: {args.output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", type=Path, default=_DEFAULT_EXCEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--check-search", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "scripts" / "client_excel_report.json")
    args = parser.parse_args()
    if not args.excel.exists():
        sys.exit(f"Excel not found: {args.excel}")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
