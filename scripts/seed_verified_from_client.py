#!/usr/bin/env python3
"""Seed verified_products from a client Excel catalog via the classify pipeline.

Usage:
  python scripts/seed_verified_from_client.py --excel path/to/sample.xlsx --dry-run
  python scripts/seed_verified_from_client.py --excel sample.xlsx --export-misses misses.json
  DATABASE_URL=postgresql://... python scripts/seed_verified_from_client.py --excel sample.xlsx
  python scripts/seed_verified_from_client.py --upsert-from data/manual_verified.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_DEFAULT_EXCEL = Path(r"c:\Users\Admin\Pictures\sample.xlsx")
if not _DEFAULT_EXCEL.exists():
    _DEFAULT_EXCEL = ROOT / "data" / "client_sample.xlsx"

_SIZE_PAT = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:G|GM|GMS|KG|KGS|ML|L|LTR|LITRE|LITER|"
    r"PC|PCS|NOS|NO|N|P|IN|MG|OZ|LB|PACK|PKT|BOX|BTL|BOTTLE|TIN|JAR|CAN|SACHET|BAG|POUCH)\b"
    r"|\b\d+\s*X\s*\d+\b|\b\d+\s*\+\s*\d+\b|\b\d+S\b|\b\d+N\b|\b\d+P\b|\b\d+\b",
    re.IGNORECASE,
)

_INVALID_HSN = frozenset({"", "UNKNOWN", "UNCLASSIFIED", "99999999", None})
_MIN_CONFIDENCE = 70


def _strip_sizes(text: str) -> str:
    t = _SIZE_PAT.sub(" ", text.upper())
    t = re.sub(r"[^A-Z\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _clean_hsn(raw: str | None) -> str | None:
    if not raw:
        return None
    d = re.sub(r"[^0-9]", "", str(raw).strip())
    return d.zfill(8) if d else None


def _clean_gst(raw: float | str | None) -> str | None:
    if raw is None:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", str(raw))
    return f"{m.group(1)}%" if m else None


def _load_excel(path: Path) -> list[str]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    names: list[str] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        val = row[0] if row else None
        if val is None:
            continue
        text = str(val).strip()
        if text:
            names.append(text)
    wb.close()
    return names


def _is_authoritative(result: dict) -> bool:
    hsn = (result.get("hsn_code") or "").strip()
    if not hsn or hsn in _INVALID_HSN:
        return False
    if result.get("gst_rate") is None:
        return False
    conf = int(result.get("confidence_score") or result.get("confidence") or 0)
    if conf < _MIN_CONFIDENCE:
        return False
    if result.get("needs_manual_review") or result.get("review_required"):
        return False
    return True


async def _classify_catalog(
    names: list[str],
    *,
    limit: int | None,
    concurrency: int,
) -> tuple[list[dict], list[dict]]:
    import app.services.gst_classifier as gst_mod
    from app.models.database import async_session, init_db
    from app.services.gst_classifier import classify

    os.environ.setdefault("SECRET_KEY", "seed-script-secret-key-32chars-min")
    os.environ.setdefault("API_KEY", "dev-api-key")
    os.environ.setdefault("ADMIN_API_KEY", "dev-admin-key")

    async def _skip_tier5_multi(_db, _query: str):
        return None

    gst_mod._tier5_multi_layer = _skip_tier5_multi

    await init_db()
    if limit:
        names = names[:limit]

    sem = asyncio.Semaphore(concurrency)
    hits: list[dict] = []
    misses: list[dict] = []

    async def _one(desc: str) -> None:
        async with sem:
            async with async_session() as db:
                try:
                    out = await classify(db, desc, bypass_cache=True)
                except Exception as exc:
                    misses.append({
                        "description": desc,
                        "reason": f"classify_error:{type(exc).__name__}",
                        "detail": str(exc)[:200],
                    })
                    return
            if _is_authoritative(out):
                hits.append({
                    "description": desc,
                    "description_normalized": desc.upper().strip(),
                    "description_no_size": _strip_sizes(desc),
                    "hsn_code": out["hsn_code"],
                    "gst_rate": _clean_gst(out.get("gst_rate")),
                    "confidence": out.get("confidence"),
                    "layer_matched": out.get("matched_layer") or out.get("source"),
                })
            else:
                misses.append({
                    "description": desc,
                    "reason": _failure_reason(out),
                    "best_hsn": out.get("hsn_code"),
                    "best_gst": out.get("gst_rate"),
                    "confidence": out.get("confidence"),
                    "layer_matched": out.get("matched_layer") or out.get("source"),
                    "needs_manual_review": out.get("needs_manual_review"),
                })

    await asyncio.gather(*[_one(n) for n in names])
    return hits, misses


def _failure_reason(out: dict) -> str:
    hsn = (out.get("hsn_code") or "").strip()
    if not hsn or hsn in _INVALID_HSN:
        return "no_hsn_match"
    if out.get("gst_rate") is None:
        return "missing_gst_rate"
    conf = int(out.get("confidence") or 0)
    if conf < _MIN_CONFIDENCE:
        return "low_confidence"
    if out.get("needs_manual_review") or out.get("review_required"):
        return "manual_review_flagged"
    return "unclassified"


def _upsert_rows(rows: list[dict], *, dry_run: bool) -> int:
    from sqlalchemy import create_engine, text

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        sys.exit("ERROR: DATABASE_URL is required for upsert.")
    db_url = (
        db_url.replace("postgres://", "postgresql://", 1)
        .replace("postgresql+asyncpg://", "postgresql://", 1)
        .replace("sqlite+aiosqlite://", "sqlite://", 1)
    )
    upsert_sql = text("""
        INSERT INTO verified_products
            (description, description_normalized, description_no_size,
             brand, category, hsn_code, gst_rate)
        VALUES
            (:description, :norm, :no_size,
             :brand, :category, :hsn_code, :gst_rate)
        ON CONFLICT (description_normalized) DO UPDATE SET
            hsn_code            = EXCLUDED.hsn_code,
            gst_rate            = EXCLUDED.gst_rate,
            description_no_size = COALESCE(EXCLUDED.description_no_size,
                                           verified_products.description_no_size),
            brand               = COALESCE(EXCLUDED.brand, verified_products.brand),
            category            = COALESCE(EXCLUDED.category, verified_products.category)
    """)
    engine = create_engine(db_url, pool_pre_ping=True)
    count = 0
    with engine.begin() as conn:
        for row in rows:
            hsn = _clean_hsn(row.get("hsn_code"))
            if not row.get("description") or not hsn:
                continue
            payload = {
                "description": row["description"],
                "norm": row.get("description_normalized") or row["description"].upper().strip(),
                "no_size": row.get("description_no_size") or _strip_sizes(row["description"]),
                "brand": row.get("brand"),
                "category": row.get("category"),
                "hsn_code": hsn,
                "gst_rate": _clean_gst(row.get("gst_rate")),
            }
            if not dry_run:
                conn.execute(upsert_sql, payload)
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed verified_products from client Excel")
    parser.add_argument("--excel", type=Path, default=_DEFAULT_EXCEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--export-misses", type=Path, default=None)
    parser.add_argument("--export-hits", type=Path, default=None)
    parser.add_argument("--upsert-from", type=Path, default=None,
                        help="JSON array of {description, hsn_code, gst_rate} rows")
    parser.add_argument(
        "--from-report",
        type=Path,
        default=None,
        help="Upsert rows marked detected=true from scripts/test_client_excel.py output",
    )
    args = parser.parse_args()

    if args.from_report:
        os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./hsn_dev.db")
        data = json.loads(args.from_report.read_text(encoding="utf-8"))
        rows = []
        for r in data.get("detected_products", []):
            rows.append({
                "description": r["description"],
                "description_normalized": r["description"].upper().strip(),
                "description_no_size": _strip_sizes(r["description"]),
                "hsn_code": r["hsn_code"],
                "gst_rate": _clean_gst(r.get("gst_rate")),
            })
        n = _upsert_rows(rows, dry_run=args.dry_run)
        print(f"{'Would upsert' if args.dry_run else 'Upserted'} {n} rows from report")
        return 0

    if args.upsert_from:
        rows = json.loads(args.upsert_from.read_text(encoding="utf-8"))
        n = _upsert_rows(rows, dry_run=args.dry_run)
        print(f"{'Would upsert' if args.dry_run else 'Upserted'} {n} rows from {args.upsert_from}")
        return 0

    if not args.excel.exists():
        sys.exit(f"Excel not found: {args.excel}")

    names = _load_excel(args.excel)
    print(f"Loaded {len(names)} product names from {args.excel}")
    hits, misses = asyncio.run(
        _classify_catalog(names, limit=args.limit, concurrency=args.concurrency)
    )
    print(f"Authoritative: {len(hits)}, Needs review / miss: {len(misses)}")

    if args.export_hits:
        args.export_hits.write_text(json.dumps(hits, indent=2), encoding="utf-8")
        print(f"Wrote {args.export_hits}")
    if args.export_misses:
        args.export_misses.write_text(json.dumps(misses, indent=2), encoding="utf-8")
        print(f"Wrote {args.export_misses}")

    if hits and not args.dry_run:
        n = _upsert_rows(hits, dry_run=False)
        print(f"Upserted {n} rows into verified_products")
    elif hits:
        print(f"Dry-run: would upsert {len(hits)} rows")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
