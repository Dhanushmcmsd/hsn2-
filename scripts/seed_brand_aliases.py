#!/usr/bin/env python3
"""Re-seed brand_aliases from CBIC FMCG brand master (alembic f1a2b3c4d5e6 data)."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_MIGRATION = ROOT / "alembic/versions/20260515_1900_f1a2b3c4d5e6_brand_aliases_and_hsn_master.py"


def _load_brand_rows() -> list[tuple]:
    spec = importlib.util.spec_from_file_location("brand_migration", _MIGRATION)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load migration: {_MIGRATION}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod._BRAND_ALIASES_FULL)


async def run() -> None:
    from sqlalchemy import text

    from app.models.database import async_session, init_db

    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        sys.exit("ERROR: DATABASE_URL must be a PostgreSQL URL (Neon)")

    brands = _load_brand_rows()
    await init_db()
    async with async_session() as db:
        for brand_name, category, hsn_code, gst_rate, cess, vsrc in brands:
            await db.execute(
                text("""
                    INSERT INTO brand_aliases
                        (brand_name, brand_name_upper, category, hsn_code,
                         gst_rate, cess_applicable, verified_source, is_active, last_updated)
                    VALUES
                        (:brand, :brand_upper, :category, :hsn_code,
                         :gst_rate, :cess, :vsrc, TRUE, NOW())
                    ON CONFLICT (brand_name_upper, hsn_code) DO UPDATE SET
                        gst_rate = EXCLUDED.gst_rate,
                        cess_applicable = EXCLUDED.cess_applicable,
                        verified_source = EXCLUDED.verified_source,
                        is_active = TRUE,
                        last_updated = NOW()
                """),
                {
                    "brand": brand_name,
                    "brand_upper": brand_name.upper().strip(),
                    "category": category,
                    "hsn_code": hsn_code,
                    "gst_rate": gst_rate,
                    "cess": cess,
                    "vsrc": vsrc,
                },
            )
        await db.commit()
        total = (await db.execute(text("SELECT COUNT(*) FROM brand_aliases"))).scalar()
        active = (
            await db.execute(
                text("SELECT COUNT(*) FROM brand_aliases WHERE is_active = TRUE")
            )
        ).scalar()
    print(f"Seeded {len(brands)} brand rows; brand_aliases total={total}, active={active}")


def main() -> int:
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
