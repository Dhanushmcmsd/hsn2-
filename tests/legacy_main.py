"""Safe access to the legacy root ``main.py`` matcher for integration tests."""
from __future__ import annotations

import os
from typing import Any, Callable


def has_live_postgres_url() -> bool:
    """True when DATABASE_URL points at Postgres (Neon/local), not sqlite stubs."""
    url = (os.environ.get("DATABASE_URL") or "").strip().lower()
    return url.startswith(("postgres://", "postgresql://", "postgresql+asyncpg://"))


def normalize_asyncpg_url(raw_url: str) -> str:
    """Normalise a Postgres URL for asyncpg + Neon pooler compatibility."""
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def get_match_one() -> Callable[..., Any]:
    """Return ``main._match_one`` after ensuring legacy main can be imported."""
    from main import _match_one

    return _match_one
