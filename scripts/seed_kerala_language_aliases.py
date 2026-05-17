#!/usr/bin/env python3
"""Seed Kerala retail Malayalam/romanized terms into language_aliases (Neon/Postgres)."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

DEFAULT_CORPUS = ROOT / "data" / "kerala_retail_aliases.json"

UPSERT_SQL = """
INSERT INTO language_aliases
    (term, term_normalized, language, hsn_code, english_term,
     weight, source, is_active, created_at)
VALUES
    (:term, :term_norm, :lang, :hsn, :english,
     :weight, :source, :is_active, NOW())
ON CONFLICT (term_normalized, language, hsn_code) DO UPDATE SET
    term = EXCLUDED.term,
    english_term = COALESCE(EXCLUDED.english_term, language_aliases.english_term),
    weight = GREATEST(language_aliases.weight, EXCLUDED.weight),
    source = EXCLUDED.source,
    is_active = TRUE
"""


async def run(corpus_path: Path, *, dry_run: bool = False) -> int:
    from sqlalchemy import text

    from app.models.database import async_session, init_db
    from app.services.kerala_seed import (
        dedupe_for_upsert,
        load_corpus,
        validate_and_normalize_corpus,
    )

    raw_entries = load_corpus(corpus_path)
    rows, errors = validate_and_normalize_corpus(raw_entries)
    if errors:
        for err in errors:
            print(f"VALIDATION ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    rows = dedupe_for_upsert(rows)
    if dry_run:
        print(f"Dry run: {len(rows)} rows validated from {corpus_path}")
        return 0

    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        sys.exit("ERROR: DATABASE_URL must be a PostgreSQL URL (Neon)")

    await init_db()
    inserted = 0
    updated = 0
    skipped = 0

    async with async_session() as db:
        for row in rows:
            params = {
                "term": row["term"],
                "term_norm": row["term_normalized"],
                "lang": row["language"],
                "hsn": row["hsn_code"],
                "english": row["english_term"],
                "weight": row["weight"],
                "source": row["source"],
                "is_active": row["is_active"],
            }
            result = await db.execute(
                text(
                    """
                    WITH upsert AS (
                        INSERT INTO language_aliases
                            (term, term_normalized, language, hsn_code, english_term,
                             weight, source, is_active, created_at)
                        VALUES
                            (:term, :term_norm, :lang, :hsn, :english,
                             :weight, :source, :is_active, NOW())
                        ON CONFLICT (term_normalized, language, hsn_code) DO UPDATE SET
                            term = EXCLUDED.term,
                            english_term = COALESCE(EXCLUDED.english_term, language_aliases.english_term),
                            weight = GREATEST(language_aliases.weight, EXCLUDED.weight),
                            source = EXCLUDED.source,
                            is_active = TRUE
                        RETURNING (xmax = 0) AS was_insert
                    )
                    SELECT was_insert FROM upsert
                    """
                ),
                params,
            )
            was_insert = result.scalar()
            if was_insert is True:
                inserted += 1
            elif was_insert is False:
                updated += 1
            else:
                skipped += 1
        await db.commit()
        total = (await db.execute(text("SELECT COUNT(*) FROM language_aliases"))).scalar()
        kerala = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*) FROM language_aliases
                    WHERE source = 'KERALA_RETAIL_CORPUS' AND is_active = TRUE
                    """
                )
            )
        ).scalar()

    print(
        f"Kerala seed complete: inserted={inserted} updated={updated} skipped={skipped} "
        f"| language_aliases total={total} | kerala_corpus_active={kerala}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Kerala retail language_aliases")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS,
        help="JSON file or directory of JSON files",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate only, no DB writes")
    args = parser.parse_args()
    if not args.corpus.exists():
        sys.exit(f"Corpus not found: {args.corpus}")
    return asyncio.run(run(args.corpus, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
