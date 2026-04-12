import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

log = structlog.get_logger()
_scheduler: AsyncIOScheduler | None = None


async def start_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.start()
    log.info("scheduler.started")


async def stop_scheduler():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
