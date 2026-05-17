#!/usr/bin/env python3
"""Smoke-test the classify pipeline for core and hard-variant product names."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./hsn_dev.db")
os.environ.setdefault("SECRET_KEY", "smoke-test-secret-key-32chars-min")
os.environ.setdefault("API_KEY", "dev-api-key")
os.environ.setdefault("ADMIN_API_KEY", "dev-admin-key")

TEST_PRODUCTS = [
    "atta", "maida", "rice", "wheat", "sugar", "salt",
    "papad", "sambar powder", "puttu podi", "rava idli mix",
    "Good Day biscuit", "Parle G biscuit", "Maggi noodles",
    "ghee", "butter", "paneer", "curd",
    "coconut water", "mango juice", "tea powder",
    "broom", "phenyl", "mosquito coil", "incense sticks",
    "coconut oil", "soap", "toothpaste",
    "rubber chappal", "jaggery", "turmeric powder",
]

HARD_VARIANTS = [
    "BULK ATTA 1KG", "NIRAPARA PUTTU PODI 1KG", "VARIYARS PUTTU PODI 1Kg",
    "MALABAR SAMBAR PDR 200g", "KARTHIKA PAPPADAM 100g",
    "GOOD DAY CASHEW BISCUITS 100g", "PARLE G GLUCOSE BISCUIT 100g",
    "MAYA ROSE INCENSE STICKS 60Pcs", "GOOD KNIGHT SHAKTI MAT MACHINE",
    "SHUDDHAKERA P.COCONUT OIL 1Ltr", "MEDAM CHILLY POWDER 500g",
    "ORGANIC NAT HIMALAYAN PINK SALT 500g", "BULK CUMIN/JEERAKAM",
    "BULK VADA PARIPPU", "MANDI RICE GOLD LOOSE",
    "VKC FTD DG9453 GENTS SLIPPER", "HAWKER WONDER SLIPPER",
    "GRANDMAS TOMATO KETCHUP 500g", "REAL MIXED FRUIT JUICE 1L",
    "HERSHEYS KISSES ALMOND 33g",
]

_INVALID_HSN = frozenset({"", "UNKNOWN", "UNCLASSIFIED", "99999999", None})


def _is_resolved(result: dict) -> bool:
    hsn = (result.get("hsn_code") or "").strip()
    if not hsn or hsn in _INVALID_HSN:
        return False
    digits = "".join(c for c in hsn if c.isdigit())
    if len(digits) not in (4, 6, 8):
        return False
    gst = result.get("gst_rate")
    if gst is None:
        return False
    return True


async def _run_batch(products: list[str], label: str) -> list[dict]:
    from app.models.database import async_session, init_db
    from app.services.gst_classifier import classify

    # Avoid reloading FAISS/matcher on every classify miss (tier-5 only).
    os.environ.setdefault("MULTI_SEARCH_TIMEOUT_FAISS_MS", "1")
    await init_db()
    rows: list[dict] = []
    async with async_session() as db:
        for name in products:
            t0 = time.perf_counter()
            try:
                out = await classify(db, name, bypass_cache=True)
            except Exception as exc:
                out = {
                    "hsn_code": None,
                    "gst_rate": None,
                    "matched_layer": f"error:{type(exc).__name__}",
                    "confidence": 0,
                    "error": str(exc)[:200],
                }
            ms = (time.perf_counter() - t0) * 1000
            hsn = out.get("hsn_code")
            gst = out.get("gst_rate")
            row = {
                "batch": label,
                "product_name": name,
                "hsn_code": hsn if hsn and str(hsn) not in _INVALID_HSN else "NOT FOUND",
                "gst_rate": gst if gst is not None else "NOT FOUND",
                "layer_matched": out.get("matched_layer") or out.get("source") or "unknown",
                "confidence": out.get("confidence_score") or out.get("confidence"),
                "time_ms": round(ms, 2),
                "needs_manual_review": out.get("needs_manual_review"),
                "resolved": _is_resolved(out),
            }
            rows.append(row)
            status = "OK" if row["resolved"] else "MISS"
            print(
                f"[{status}] {name[:40]:<40} hsn={row['hsn_code']!s:<12} "
                f"gst={row['gst_rate']!s:<6} layer={row['layer_matched']}"
            )
    return rows


def _summarize(rows: list[dict], title: str) -> dict:
    resolved = [r for r in rows if r["resolved"]]
    not_found = [r["product_name"] for r in rows if not r["resolved"]]
    times = [r["time_ms"] for r in rows]
    summary = {
        "title": title,
        "total": len(rows),
        "resolved": len(resolved),
        "not_found_count": len(not_found),
        "not_found": not_found,
        "avg_time_ms": round(sum(times) / len(times), 2) if times else 0,
    }
    print(f"\n=== {title} ===")
    print(f"Total: {summary['total']}, Resolved: {summary['resolved']}, Not found: {summary['not_found_count']}")
    if not_found:
        print("Not found:", ", ".join(not_found))
    print(f"Average response time: {summary['avg_time_ms']} ms")
    return summary


async def main() -> int:
    core_rows = await _run_batch(TEST_PRODUCTS, "core")
    hard_rows = await _run_batch(HARD_VARIANTS, "hard")
    all_rows = core_rows + hard_rows
    core_summary = _summarize(core_rows, "Core products (30)")
    hard_summary = _summarize(hard_rows, "Hard variants (20)")

    payload = {
        "core": core_summary,
        "hard": hard_summary,
        "rows": all_rows,
    }
    out_path = ROOT / "scripts" / "smoke_test_results.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0 if core_summary["resolved"] == 30 and hard_summary["resolved"] >= 18 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
