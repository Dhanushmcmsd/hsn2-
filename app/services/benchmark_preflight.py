"""Shared benchmark preflight: detect Neon seed state before 'after' metrics.

Kerala corpus seeding is explicit (scripts/seed_kerala_language_aliases.py).
Benchmarks must not auto-seed — use --require-kerala-corpus for production-safe runs.
See docs/KERALA_SEARCH_POLICY.md.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[2]
KERALA_CORPUS_JSON = ROOT / "data" / "kerala_retail_aliases.json"
KERALA_CORPUS_SOURCE = "KERALA_RETAIL_CORPUS"


def expected_kerala_corpus_rows() -> int:
    if not KERALA_CORPUS_JSON.exists():
        return 0
    return len(json.loads(KERALA_CORPUS_JSON.read_text(encoding="utf-8")))


async def collect_benchmark_metadata(db: AsyncSession | None, database_url: str) -> dict[str, Any]:
    """Environment snapshot for Excel / smoke benchmarks."""
    is_postgres = database_url.startswith("postgresql") or database_url.startswith("postgres://")
    try:
        from app.services.kerala_corpus_hints import corpus_stats
        from app.services.kerala_corpus_maps import corpus_maps_stats

        corpus_hint_stats = {**corpus_stats(), **corpus_maps_stats()}
    except Exception:
        corpus_hint_stats = {}

    json_rows = expected_kerala_corpus_rows()
    meta: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "database_url_scheme": database_url.split(":", 1)[0],
        "dialect": "postgresql" if is_postgres else ("sqlite" if "sqlite" in database_url else "other"),
        "expected_kerala_corpus_rows": json_rows,
        "kerala_corpus_json_row_count": json_rows,
        "kerala_corpus_json_stats": corpus_hint_stats,
        "kerala_corpus_seeded": False,
        "kerala_corpus_seed_required": False,
        "language_aliases_count": None,
        "kerala_corpus_count": None,
        "kerala_corpus_db_row_count": None,
        "brand_aliases_count": None,
        "seed_status": "",
        "warnings": [],
    }

    if db is None or not is_postgres:
        if is_postgres:
            meta["warnings"].append(
                "Postgres selected but no DB session — run diagnose_db_environment.py before Neon benchmarks."
            )
        else:
            meta["warnings"].append(
                "SQLite dev DB: language_aliases Kerala rows are not in Postgres — "
                "'after' hit-rates are not comparable to production Neon."
            )
        return meta

    try:
        meta["language_aliases_count"] = (
            await db.execute(text("SELECT COUNT(*) FROM language_aliases"))
        ).scalar()
        meta["kerala_corpus_count"] = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*) FROM language_aliases
                    WHERE source = :src AND is_active = TRUE
                    """
                ),
                {"src": KERALA_CORPUS_SOURCE},
            )
        ).scalar()
        meta["brand_aliases_count"] = (
            await db.execute(text("SELECT COUNT(*) FROM brand_aliases"))
        ).scalar()
    except Exception as exc:
        meta["warnings"].append(f"Could not read alias counts: {exc!s}"[:200])
        return meta

    from app.services.kerala_search_policy import is_kerala_corpus_seed_required, seed_status_summary

    expected = meta["expected_kerala_corpus_rows"]
    count = int(meta["kerala_corpus_count"] or 0)
    meta["kerala_corpus_db_row_count"] = count
    meta["kerala_corpus_seeded"] = count >= max(expected - 5, int(expected * 0.9))
    meta["kerala_corpus_seed_required"] = is_kerala_corpus_seed_required(meta)
    meta["seed_status"] = seed_status_summary(meta)

    if expected > 0 and count < int(expected * 0.5):
        meta["warnings"].append(
            f"Kerala corpus critically low: DB has {count} rows, expected ~{expected} "
            "(below 50% — benchmarks are unreliable)."
        )
    elif not meta["kerala_corpus_seeded"]:
        meta["warnings"].append(
            f"Kerala corpus under-seeded: DB has {count} rows, expected ~{expected}. "
            "Run: python scripts/seed_kerala_language_aliases.py"
        )

    return meta


def enforce_kerala_corpus_preflight(meta: dict[str, Any], *, require: bool) -> None:
    """Raise SystemExit when --require-kerala-corpus and Neon corpus is missing."""
    if not require:
        return
    if meta.get("dialect") != "postgresql":
        raise SystemExit("--require-kerala-corpus needs Postgres/Neon (use --neon).")
    if not meta.get("kerala_corpus_seeded"):
        raise SystemExit(
            "Kerala corpus not seeded in this database. "
            f"{meta.get('seed_status', '')} "
            "Run: python scripts/seed_kerala_language_aliases.py "
            "then: python scripts/verify_neon_seed_counts.py"
        )
