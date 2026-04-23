import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


DATABASE_URL = os.environ["DATABASE_URL"]
if not DATABASE_URL.startswith("postgresql+asyncpg"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    DATABASE_URL,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "ssl": "require",
    },
)


async def audit() -> None:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM hsn_codes WHERE is_active = TRUE"))
        print(f"Active HSN codes: {result.scalar()}")

        result = await conn.execute(text("SELECT COUNT(*) FROM verified_products"))
        print(f"Verified products: {result.scalar()}")

        result = await conn.execute(text(
            "SELECT COUNT(*) FROM hsn_codes WHERE description IS NULL OR description = ''"
        ))
        print(f"HSN codes with empty description: {result.scalar()}")

        result = await conn.execute(text(
            "SELECT COUNT(*) FROM verified_products WHERE description_no_size IS NULL"
        ))
        print(f"Verified products with NULL description_no_size: {result.scalar()}")

        result = await conn.execute(text("""
            SELECT hsn_code, description, gst_rate
            FROM hsn_codes
            WHERE description ILIKE '%juice%'
            ORDER BY hsn_code
            LIMIT 10
        """))
        print("\nAll 'juice' entries in hsn_codes:")
        for row in result.fetchall():
            print(f"  {row.hsn_code} | GST:{row.gst_rate} | {row.description[:80]}")

        result = await conn.execute(text("""
            SELECT hsn_code, description, gst_rate
            FROM verified_products
            WHERE description_normalized ILIKE '%JUICE%'
            LIMIT 10
        """))
        print("\nAll 'JUICE' entries in verified_products:")
        for row in result.fetchall():
            print(f"  {row.hsn_code} | GST:{row.gst_rate} | {row.description[:80]}")

        result = await conn.execute(text("""
            SELECT SUBSTRING(hsn_code, 1, 2) AS chapter, COUNT(*) AS count
            FROM hsn_codes
            WHERE is_active = TRUE
            GROUP BY chapter
            ORDER BY count DESC
            LIMIT 20
        """))
        print("\nTop chapters in hsn_codes DB:")
        for row in result.fetchall():
            print(f"  Ch{row.chapter}: {row.count} codes")


if __name__ == "__main__":
    asyncio.run(audit())
