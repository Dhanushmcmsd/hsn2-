"""Log UNCLASSIFIED products for active learning (Postgres only)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

log = structlog.get_logger()


async def log_miss(
    db: AsyncSession,
    product_name: str,
    normalized_name: str | None = None,
) -> None:
    """UPSERT into miss_log; never raises."""
    try:
        from app.config import settings
        if "sqlite" in (settings.DATABASE_URL or "").lower():
            return

        first_token = product_name.strip().upper().split()[0] if product_name.strip() else None
        await db.execute(
            text("""
                INSERT INTO miss_log (product_name, normalized_name, first_token, hit_count, updated_at)
                VALUES (:name, :norm, :tok, 1, NOW())
                ON CONFLICT (product_name) DO UPDATE SET
                  hit_count = miss_log.hit_count + 1,
                  normalized_name = COALESCE(EXCLUDED.normalized_name, miss_log.normalized_name),
                  first_token = COALESCE(EXCLUDED.first_token, miss_log.first_token),
                  updated_at = NOW()
            """),
            {
                "name": product_name[:500],
                "norm": (normalized_name or product_name)[:500],
                "tok": (first_token or "")[:100],
            },
        )
        await db.commit()
    except Exception as exc:
        log.debug("miss_logger.failed", error=str(exc)[:120])
