#!/usr/bin/env python3
"""Seed language_aliases from in-memory hsn_master product alias dict (L0 alias_dict)."""
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
    from app.services.hsn_master import _VERIFIED_PRODUCT_ALIASES, canonicalize_hsn

    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        sys.exit("ERROR: DATABASE_URL must be a PostgreSQL URL (Neon)")

    await init_db()
    inserted = 0
    async with async_session() as db:
        for alias, hsn in sorted(_VERIFIED_PRODUCT_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
            code = canonicalize_hsn(hsn) or hsn
            term_norm = alias.upper().strip()
            await db.execute(
                text("""
                    INSERT INTO language_aliases
                        (term, term_normalized, language, hsn_code, english_term,
                         weight, source, is_active, created_at)
                    VALUES
                        (:term, :term_norm, 'en', :hsn, :term,
                         90, 'L0_ALIAS_DICT_SEED', TRUE, NOW())
                    ON CONFLICT (term_normalized, language, hsn_code) DO NOTHING
                """),
                {"term": alias, "term_norm": term_norm, "hsn": code},
            )
            inserted += 1
        await db.commit()
        row = (await db.execute(text("SELECT COUNT(*) FROM language_aliases"))).scalar()
    print(f"Upserted {inserted} alias terms; language_aliases total={row}")


def main() -> int:
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
