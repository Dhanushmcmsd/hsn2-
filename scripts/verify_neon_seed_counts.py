#!/usr/bin/env python3
"""Verify language_aliases and brand_aliases counts on Neon/Postgres."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


async def run() -> None:
    from sqlalchemy import text

    from app.models.database import async_session, init_db
    from app.services.benchmark_preflight import expected_kerala_corpus_rows

    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        sys.exit("ERROR: DATABASE_URL must be a PostgreSQL URL")

    expected_json = expected_kerala_corpus_rows()

    await init_db()
    async with async_session() as db:
        lang = (await db.execute(text("""
            SELECT COUNT(*), MIN(created_at), MAX(created_at)
            FROM language_aliases
        """))).first()
        brands = (await db.execute(text("""
            SELECT is_active, COUNT(*) FROM brand_aliases GROUP BY is_active
        """))).all()
        total_brands = (await db.execute(text("SELECT COUNT(*) FROM brand_aliases"))).scalar()
        by_lang = (
            await db.execute(
                text(
                    """
                    SELECT language, COUNT(*) AS n
                    FROM language_aliases
                    WHERE is_active = TRUE
                    GROUP BY language
                    ORDER BY n DESC
                    """
                )
            )
        ).all()
        kerala_n = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*) FROM language_aliases
                    WHERE source = 'KERALA_RETAIL_CORPUS' AND is_active = TRUE
                    """
                )
            )
        ).scalar()
        samples = (
            await db.execute(
                text(
                    """
                    SELECT term, language, english_term, hsn_code, weight
                    FROM language_aliases
                    WHERE source = 'KERALA_RETAIL_CORPUS'
                    ORDER BY weight DESC
                    LIMIT 5
                    """
                )
            )
        ).mappings().all()

    print(f"language_aliases: count={lang[0]}, min_created={lang[1]}, max_created={lang[2]}")
    print(f"brand_aliases total={total_brands}")
    for row in brands:
        print(f"  is_active={row[0]} count={row[1]}")
    if total_brands == 0:
        print("WARNING: brand_aliases is empty — Tier 1 exact brand match is dead on Neon.")

    print("\nlanguage_aliases by language (active):")
    for row in by_lang:
        print(f"  {row[0]}: {row[1]}")
    print(f"Kerala corpus (KERALA_RETAIL_CORPUS): {kerala_n} active rows")
    print(f"Expected from data/kerala_retail_aliases.json: ~{expected_json}")
    if expected_json and kerala_n < int(expected_json * 0.9):
        print(
            f"WARNING: under-seeded (have {kerala_n}, expected ~{expected_json}). "
            "Run: python scripts/seed_kerala_language_aliases.py"
        )
    elif expected_json and kerala_n >= expected_json - 5:
        print("OK: Kerala corpus count matches JSON within tolerance.")
    if samples:
        print("Sample Kerala rows:")
        for s in samples:
            print(f"  [{s['language']}] {s['term']!r} -> {s['english_term']!r} HSN={s['hsn_code']}")


def main() -> int:
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
