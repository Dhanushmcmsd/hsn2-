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

    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        sys.exit("ERROR: DATABASE_URL must be a PostgreSQL URL")

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

    print(f"language_aliases: count={lang[0]}, min_created={lang[1]}, max_created={lang[2]}")
    print(f"brand_aliases total={total_brands}")
    for row in brands:
        print(f"  is_active={row[0]} count={row[1]}")
    if total_brands == 0:
        print("WARNING: brand_aliases is empty — Tier 1 exact brand match is dead on Neon.")


def main() -> int:
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
