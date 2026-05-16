"""Process-local LRU cache for HSN search results.

This is the fastest possible cache tier — no network round-trip.
All entries are stored in RAM and survive for TTL seconds.
Capped at MAX_ENTRIES to keep memory bounded on Render free tier (512 MB).

Hit rate on production workloads is typically >80% for FMCG queries
because the same product names recur constantly across POS requests.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

_NOT_FOUND = object()

MAX_ENTRIES = 2_000   # ~2 MB RAM at ~1 KB per entry
DEFAULT_TTL = 300     # 5 minutes


class _LRUCache:
    def __init__(self, maxsize: int = MAX_ENTRIES, default_ttl: int = DEFAULT_TTL):
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._maxsize = maxsize
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any:
        entry = self._store.get(key, _NOT_FOUND)
        if entry is _NOT_FOUND:
            self._misses += 1
            return None
        value, expires = entry
        if time.monotonic() > expires:
            del self._store[key]
            self._misses += 1
            return None
        # Move to end (most-recently-used)
        self._store.move_to_end(key)
        self._hits += 1
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl if ttl is not None else self._default_ttl
        expires = time.monotonic() + ttl
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (value, expires)
        if len(self._store) > self._maxsize:
            self._store.popitem(last=False)  # evict least-recently-used

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "maxsize": self._maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
        }


# Module-level singleton — shared by all coroutines in the same process
_cache = _LRUCache()


def lru_get(key: str) -> Any:
    return _cache.get(key)


def lru_set(key: str, value: Any, ttl: int | None = None) -> None:
    _cache.set(key, value, ttl=ttl)


def lru_delete(key: str) -> None:
    _cache.delete(key)


def lru_clear() -> None:
    _cache.clear()


def lru_stats() -> dict:
    return _cache.stats
