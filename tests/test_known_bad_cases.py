import asyncio
import os

import pytest

from tests.legacy_main import get_match_one, has_live_postgres_url, normalize_asyncpg_url


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not has_live_postgres_url(),
        reason="Postgres DATABASE_URL required for live matcher verification",
    ),
]


KNOWN_BAD_CASES = [
    ("juice", "22"),
    ("harpic", "34"),
    ("sesame oil", "15"),
    ("fruit jam", "20"),
    ("cashew cookie", "19"),
    ("horlicks womens", "21"),
    ("vkc chappal", "64"),
    ("basmati rice", "10"),
]


@pytest.mark.asyncio
async def test_known_bad_cases_resolve_to_expected_chapters():
    database_url = normalize_asyncpg_url(os.environ["DATABASE_URL"])

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    _match_one = get_match_one()
    engine = create_async_engine(
        database_url,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "ssl": "require",
        },
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        for query, expected_chapter in KNOWN_BAD_CASES:
            result = await _match_one(query, db)
            assert result.hsn_code, f"{query!r} returned no HSN result"
            assert result.hsn_code[:2] == expected_chapter, (
                f"{query!r} resolved to {result.hsn_code} via {result.match_method} "
                f"(confidence={result.confidence:.2f}), expected chapter {expected_chapter}"
            )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_known_bad_cases_resolve_to_expected_chapters())
