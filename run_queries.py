import asyncio
from sqlalchemy import text
from app.models.database import engine

async def run_queries():
    async with engine.begin() as conn:
        print("--- TABLES ---")
        res = await conn.execute(text("SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC"))
        for row in res.fetchall(): print(row)

        print("--- COLUMNS ---")
        res = await conn.execute(text("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"))
        for row in res.fetchall(): print(row)

        print("--- INDEXES ---")
        res = await conn.execute(text("SELECT indexname, tablename, indexdef FROM pg_indexes WHERE schemaname = 'public'"))
        for row in res.fetchall(): print(row)

        print("--- EXTENSIONS ---")
        res = await conn.execute(text("SELECT extname FROM pg_extension"))
        for row in res.fetchall(): print(row)

        print("--- PREDICTIONS SOURCE COUNT ---")
        res = await conn.execute(text("SELECT source, COUNT(*) FROM predictions GROUP BY source"))
        for row in res.fetchall(): print(row)

        print("--- SAMPLE FROM LARGEST TABLE (hsn_codes or verified_products) ---")
        res = await conn.execute(text("SELECT hsn_code, description FROM verified_products LIMIT 20"))
        for row in res.fetchall(): print(row)

asyncio.run(run_queries())
