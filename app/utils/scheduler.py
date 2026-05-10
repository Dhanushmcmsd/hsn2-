from __future__ import annotations

import time
import logging
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --- GST SYNC START ---
from sqlalchemy import select, text

from app.models.database import async_session, HsnCode
from app.services.gst_fetcher import fetch_all_gst_rates
from app.utils.metrics import gst_sync_last_run_timestamp, gst_sync_updated_total
# --- GST SYNC END ---

log = structlog.get_logger()
_scheduler: AsyncIOScheduler | None = None


# --- GST SYNC START ---
async def sync_gst_rates() -> dict:
    """
    Core GST sync job:
      1. Fetch all GST rates via 3-layer fallback (gst_fetcher.py)
      2. For each HSN code, compare with DB and update if changed / NULL
      3. Insert a row into gst_change_log for every changed rate
      4. Log summary and update Prometheus gauges
    Returns a stats dict (also used by trigger_gst_sync_now).
    """
    started_at = time.monotonic()
    logger = logging.getLogger(__name__)

    try:
        rates = await fetch_all_gst_rates()
    except Exception as exc:
        logger.error("GST_SYNC: fetch_all_gst_rates failed: %s", exc)
        raise

    updated = 0
    unchanged = 0
    source_seen: set[str] = set()

    try:
        async with async_session() as session:
            result = await session.execute(select(HsnCode))
            db_rows: dict[str, HsnCode] = {
                row.hsn_code: row for row in result.scalars().all()
            }

            change_log_rows: list[dict] = []

            for hsn_code, gst_data in rates.items():
                new_rate = float(gst_data["rate"])
                new_eff_from = gst_data["effective_from"]
                src = gst_data["source"]
                source_seen.add(src)

                row = db_rows.get(hsn_code)
                if row is None:
                    unchanged += 1
                    continue

                old_rate = (
                    float(row.gst_rate_numeric)
                    if row.gst_rate_numeric is not None
                    else None
                )

                rate_changed = (old_rate is None) or (abs(old_rate - new_rate) > 1e-4)

                if rate_changed:
                    row.gst_rate_numeric = new_rate
                    row.gst_effective_from = new_eff_from
                    row.gst_updated_at = datetime.now(timezone.utc)

                    change_log_rows.append(
                        {
                            "hsn_code": hsn_code,
                            "old_rate": old_rate,
                            "new_rate": new_rate,
                            "source": src,
                        }
                    )
                    updated += 1
                else:
                    unchanged += 1

            if change_log_rows:
                try:
                    await session.execute(
                        text(
                            """
                            INSERT INTO gst_change_log
                                (hsn_code, old_rate, new_rate, source, changed_at)
                            VALUES
                                (:hsn_code, :old_rate, :new_rate, :source, NOW())
                            """
                        ),
                        change_log_rows,
                    )
                except Exception as log_exc:
                    logger.warning(
                        "GST_SYNC: gst_change_log insert failed (table may not exist yet): %s",
                        log_exc,
                    )

            await session.commit()

    except Exception as exc:
        logger.error("GST_SYNC: DB update failed: %s", exc)
        raise

    duration_ms = int((time.monotonic() - started_at) * 1000)
    primary_source = next(iter(source_seen), "unknown")

    logger.info(
        "GST_SYNC: updated %d rates, %d unchanged, source=%s, duration=%dms",
        updated,
        unchanged,
        primary_source,
        duration_ms,
    )

    # ── Prometheus gauges ──────────────────────────────────────────────────
    gst_sync_last_run_timestamp.set(time.time())
    gst_sync_updated_total.set(updated)
    # ───────────────────────────────────────────────────────────────────────

    return {
        "updated": updated,
        "unchanged": unchanged,
        "source": primary_source,
        "duration_ms": duration_ms,
    }


async def trigger_gst_sync_now() -> dict:
    """
    Manual trigger for the GST sync job.
    Returns {updated, unchanged, source, duration_ms}.
    """
    log.info("GST_SYNC: manual trigger invoked")
    return await sync_gst_rates()
# --- GST SYNC END ---


async def start_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()

    # --- GST SYNC START ---
    _scheduler.add_job(
        sync_gst_rates,
        trigger=CronTrigger(
            hour=2,
            minute=0,
            timezone="Asia/Kolkata",
        ),
        id="gst_nightly_sync",
        name="Nightly GST rate sync (02:00 IST)",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    log.info("scheduler.gst_nightly_sync_registered", schedule="02:00 IST daily")
    # --- GST SYNC END ---

    _scheduler.start()
    log.info("scheduler.started")


async def stop_scheduler():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
