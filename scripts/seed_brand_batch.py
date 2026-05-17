#!/usr/bin/env python3
"""Infer brand_aliases + verified_products from undetected catalog via classify pipeline."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_MIN_CONFIDENCE = 65


def _load_undetected(report_path: str, excel_path: str | None) -> list[str]:
    if excel_path and Path(excel_path).exists():
        import openpyxl
        wb = openpyxl.load_workbook(excel_path, read_only=True)
        ws = wb.active
        names = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue
            if row and row[0]:
                names.append(str(row[0]).strip())
        wb.close()
        return names

    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    return [r["description"] for r in data.get("undetected_products", [])]


async def infer_hsn_for_product(db, product_name: str) -> dict | None:
    from app.services.gst_classifier import classify

    try:
        result = await classify(db, product_name, bypass_cache=True)
        if result and result.get("hsn_code") and int(result.get("confidence", 0)) >= _MIN_CONFIDENCE:
            hsn = str(result["hsn_code"])
            if hsn not in ("UNCLASSIFIED", "UNKNOWN", ""):
                return result
    except Exception:
        pass
    return None


async def run_seed(source: str, *, dry_run: bool, min_freq: int, excel: str | None) -> None:
    from sqlalchemy import text
    from app.models.database import async_session, init_db

    os.environ.setdefault("SECRET_KEY", "seed-brand-secret-key-32chars-min")
    os.environ.setdefault("API_KEY", "dev-api-key")
    os.environ.setdefault("ADMIN_API_KEY", "dev-admin-key")

    await init_db()
    undetected = _load_undetected(source, excel)
    groups: dict[str, list[str]] = defaultdict(list)
    for name in undetected:
        tok = name.strip().upper().split()[0] if name.strip() else ""
        if tok and len(tok) >= 2:
            groups[tok].append(name)

    ranked = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)
    seeded_brands = 0
    seeded_products = 0

    async with async_session() as db:
        for brand_token, products_list in ranked:
            if len(products_list) < min_freq:
                continue
            representative = sorted(products_list, key=len)[len(products_list) // 2]
            result = await infer_hsn_for_product(db, representative)
            if not result:
                print(f"  SKIP {brand_token:20s} ({len(products_list):4d} products) — no HSN")
                continue

            hsn = re.sub(r"[^0-9]", "", str(result["hsn_code"]))[:8].zfill(8)
            gst = float(result.get("gst_rate") or 0.0)
            confidence = int(result.get("confidence", 0))
            print(
                f"  SEED {brand_token:20s} ({len(products_list):4d} products) "
                f"→ {hsn} ({gst}% GST) conf={confidence}"
            )

            if dry_run:
                continue

            await db.execute(
                text("""
                    INSERT INTO brand_aliases
                        (brand_name, brand_name_upper, category, hsn_code, gst_rate,
                         cess_applicable, verified_source, is_active)
                    VALUES
                        (:brand, :brand_upper, :cat, :hsn, :gst, FALSE, 'brand_batch_seed', TRUE)
                    ON CONFLICT (brand_name_upper, hsn_code) DO UPDATE SET
                        gst_rate = EXCLUDED.gst_rate,
                        verified_source = EXCLUDED.verified_source
                """),
                {
                    "brand": brand_token.title(),
                    "brand_upper": brand_token,
                    "cat": result.get("description", brand_token)[:100],
                    "hsn": hsn,
                    "gst": gst,
                },
            )
            seeded_brands += 1

            for pname in products_list[:50]:
                desc_norm = pname.upper().strip()
                gst_str = f"{gst:g}%"
                await db.execute(
                    text("""
                        INSERT INTO verified_products
                            (description, description_normalized, description_no_size,
                             brand, hsn_code, gst_rate)
                        VALUES
                            (:desc, :norm, :no_size, :brand, :hsn, :gst)
                        ON CONFLICT (description_normalized) DO UPDATE SET
                            hsn_code = EXCLUDED.hsn_code,
                            gst_rate = EXCLUDED.gst_rate,
                            brand = EXCLUDED.brand
                    """),
                    {
                        "desc": pname,
                        "norm": desc_norm,
                        "no_size": desc_norm,
                        "brand": brand_token,
                        "hsn": hsn,
                        "gst": gst_str,
                    },
                )
                seeded_products += 1
            await db.commit()

    print(f"\nDone: {seeded_brands} brand aliases, {seeded_products} verified_products")
    if dry_run:
        print("(DRY RUN — nothing written)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="scripts/client_excel_report.json")
    parser.add_argument("--excel", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-freq", type=int, default=2)
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        sys.exit("ERROR: DATABASE_URL is required")

    asyncio.run(run_seed(args.report, dry_run=args.dry_run, min_freq=args.min_freq, excel=args.excel))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
