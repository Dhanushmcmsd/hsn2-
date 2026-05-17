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
    ("L0 alias_dict", ("L0_alias_dict", "L1_brand_alias", "in_memory_alias", "L0_alias_dict")),
    ("L1 brand_aliases", ("brand_alias", "L1_brand_alias")),
    ("L3 curated_master", ("L3_curated_master", "curated_master")),
    ("L4 tariff_fallback", ("L4_tariff_fallback", "tariff", "inverted", "multi_layer")),
    ("L5 keyword_fallback", ("L5_keyword_fallback", "keyword_hsn_search")),
    ("UNCLASSIFIED", ("L6_pending_review", "pending_review", "UNCLASSIFIED")),
)


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


async def main_async(args: argparse.Namespace) -> int:
    if args.neon:
        _load_env_neon()

    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./hsn_dev.db")
    is_postgres = "postgresql" in database_url
    skip_faiss = not is_postgres

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

    report = {
        "excel": str(args.excel),
        "database": "neon" if is_postgres else "sqlite",
        "total_products": len(rows),
        "detected": len(detected),
        "undetected": len(missed),
        "detection_score_pct": score_pct,
        "undetected_products": missed,
        "detected_products": detected,
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not args.quick:
        print(f"Report: {args.output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", type=Path, default=_DEFAULT_EXCEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--neon", action="store_true")
    parser.add_argument(
        "--skip-faiss",
        action="store_true",
        help="Skip FAISS tier-5 warm-up (faster run to test L3/L4/L5 only)",
    )
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output", type=Path, default=ROOT / "scripts" / "client_excel_report.json")
    args = parser.parse_args()
    if args.quick and not args.sample:
        args.sample = 200
    if not args.excel.exists():
        sys.exit(f"Excel not found: {args.excel}")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
