#!/usr/bin/env python3
"""Report DB dialect, Postgres capabilities, and Kerala/Malayalam layer availability."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


async def run() -> int:
    from sqlalchemy import text

    from app.models.database import async_session, init_db

    _load_env()
    url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./hsn_dev.db")
    is_postgres = url.startswith("postgresql") or url.startswith("postgres://")
    is_sqlite = "sqlite" in url

    report: dict = {
        "database_url_scheme": url.split(":", 1)[0],
        "dialect": "postgresql" if is_postgres else ("sqlite" if is_sqlite else "other"),
        "pg_trgm_available": False,
        "language_aliases_count": None,
        "language_aliases_by_language": {},
        "kerala_corpus_count": None,
        "brand_aliases_count": None,
        "layers_disabled_on_sqlite": [
            "language_aliases DB table (not created on SQLite migrations)",
            "pg_trgm fuzzy search",
            "aliases.expand_query fuzzy resolver",
            "pg_search keyword_hsn_search",
            "brand_search tier-2 fuzzy (requires pg_trgm)",
        ],
        "local_kerala_json_fallback": False,
    }

    from app.services.benchmark_preflight import expected_kerala_corpus_rows

    report["expected_kerala_corpus_rows"] = expected_kerala_corpus_rows()
    corpus_path = ROOT / "data" / "kerala_retail_aliases.json"
    report["local_kerala_json_fallback"] = corpus_path.exists()
    if report["local_kerala_json_fallback"]:
        report["local_kerala_json_entries"] = report["expected_kerala_corpus_rows"]

    await init_db()

    if is_postgres:
        async with async_session() as db:
            from app.services.benchmark_preflight import collect_benchmark_metadata

            meta = await collect_benchmark_metadata(db, url)
            report.update(
                {
                    "kerala_corpus_seeded": meta.get("kerala_corpus_seeded"),
                    "expected_kerala_corpus_rows": meta.get("expected_kerala_corpus_rows"),
                    "warnings": meta.get("warnings", []),
                }
            )
            try:
                ext = (
                    await db.execute(
                        text(
                            "SELECT EXISTS("
                            "  SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"
                            ") AS ok"
                        )
                    )
                ).scalar()
                report["pg_trgm_available"] = bool(ext)
            except Exception as exc:
                report["pg_trgm_error"] = str(exc)[:200]

            try:
                report["language_aliases_count"] = (
                    await db.execute(text("SELECT COUNT(*) FROM language_aliases"))
                ).scalar()
                rows = (
                    await db.execute(
                        text(
                            """
                            SELECT language, COUNT(*) AS n
                            FROM language_aliases
                            WHERE is_active = TRUE
                            GROUP BY language
                            ORDER BY n DESC
                            """
                        )
                    )
                ).all()
                report["language_aliases_by_language"] = {r[0]: r[1] for r in rows}
                report["kerala_corpus_count"] = (
                    await db.execute(
                        text(
                            """
                            SELECT COUNT(*) FROM language_aliases
                            WHERE source = 'KERALA_RETAIL_CORPUS' AND is_active = TRUE
                            """
                        )
                    )
                ).scalar()
                report["brand_aliases_count"] = (
                    await db.execute(text("SELECT COUNT(*) FROM brand_aliases"))
                ).scalar()
                samples = (
                    await db.execute(
                        text(
                            """
                            SELECT term, language, english_term, hsn_code, weight
                            FROM language_aliases
                            WHERE source = 'KERALA_RETAIL_CORPUS'
                            ORDER BY weight DESC
                            LIMIT 5
                            """
                        )
                    )
                ).mappings().all()
                report["kerala_corpus_sample"] = [dict(r) for r in samples]
            except Exception as exc:
                report["language_aliases_error"] = str(exc)[:200]
    else:
        from app.services.aliases import local_kerala_fallback_stats

        report["local_kerala_fallback_stats"] = local_kerala_fallback_stats()

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
