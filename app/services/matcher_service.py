"""Background singleton HybridMatcher — avoids blocking first admin/search request."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger()


class MatcherService:
    def __init__(self) -> None:
        self.ready: bool = False
        self.loading: bool = False
        self.failed: bool = False
        self.last_error: str | None = None
        self.load_started_at: datetime | None = None
        self.load_completed_at: datetime | None = None
        self.load_time_ms: float | None = None
        self._matcher = None
        self._warmup_lock = threading.Lock()
        self._state_lock = threading.Lock()

    def start_warmup(self) -> None:
        with self._state_lock:
            if self.ready or self.loading or self.failed:
                return
            self.loading = True
            self.load_started_at = datetime.now(timezone.utc)
        log.info("matcher.warmup_start")
        threading.Thread(target=self._load_worker, name="matcher-warmup", daemon=True).start()

    def is_ready(self) -> bool:
        return self.ready and self._matcher is not None

    def get(self):
        if self.is_ready():
            return self._matcher
        return None

    def status_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "loading": self.loading,
            "failed": self.failed,
            "load_time_ms": self.load_time_ms,
            "last_error": self.last_error,
        }

    def _load_worker(self) -> None:
        with self._warmup_lock:
            started = time.perf_counter()
            try:
                from app.services.matcher import HybridMatcher

                self._matcher = HybridMatcher()
                elapsed = (time.perf_counter() - started) * 1000
                with self._state_lock:
                    self.ready = True
                    self.loading = False
                    self.load_completed_at = datetime.now(timezone.utc)
                    self.load_time_ms = round(elapsed, 2)
                log.info("matcher.warmup_success", load_time_ms=self.load_time_ms)
            except Exception as exc:
                err = str(exc)[:500]
                with self._state_lock:
                    self.failed = True
                    self.loading = False
                    self.last_error = err
                    self.load_time_ms = round((time.perf_counter() - started) * 1000, 2)
                log.warning("matcher.warmup_failed", error=err)


_service: MatcherService | None = None
_lock = threading.Lock()


def get_matcher_service() -> MatcherService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = MatcherService()
    return _service
