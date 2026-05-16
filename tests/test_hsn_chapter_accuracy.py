import asyncio
import os

import pytest

from tests.legacy_main import get_match_one, has_live_postgres_url, normalize_asyncpg_url


CHAPTER_ACCURACY_CASES = [
    ("fruit juice", "22"),
    ("juice", "22"),
    ("orange juice", "20"),
    ("harpic", "34"),
    ("harpic bathroom cleaner", "34"),
    ("colgate toothpaste", "33"),
    ("vkc chappal", "64"),
    ("vkc slipper", "64"),
    ("basmati rice", "10"),
    ("matta rice", "10"),
    ("wheat atta", "11"),
    ("sunflower oil", "15"),
    ("sesame oil", "15"),
    ("gingelly oil", "15"),
    ("amul butter", "04"),
    ("fresh milk", "04"),
    ("cashew cookie", "19"),
    ("fruit jam", "20"),
    ("mixed fruit jam", "20"),
    ("dark chocolate", "18"),
    ("jaggery", "17"),
    ("horlicks", "21"),
    ("turmeric powder", "09"),
    ("red chilli powder", "09"),
    ("agarbatti", "33"),
    ("shampoo", "33"),
    ("soap", "34"),
    ("detergent", "34"),
    ("notebook", "48"),
    ("pen", "96"),
    ("toy car", "95"),
    ("umbrella", "66"),
    ("iphone", "85"),
    ("laptop", "84"),
    ("sugar", "17"),
    ("salt iodized", "25"),
]


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not has_live_postgres_url(),
        reason="Postgres DATABASE_URL required for live chapter-accuracy verification",
    ),
]


def _chapter_ok(actual: str, expected: str) -> bool:
    return (
        actual == expected
        or (expected in {"20", "21", "22"} and actual in {"20", "21", "22"})
        or (expected == "33" and actual in {"33", "34"})
        or (expected == "34" and actual in {"33", "34"})
    )


@pytest.mark.asyncio
async def test_hsn_chapter_accuracy():
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
        for query, expected_chapter in CHAPTER_ACCURACY_CASES:
            result = await _match_one(query, db)
            assert result.hsn_code, f"{query!r} returned no HSN result"
            actual = result.hsn_code[:2]
            assert _chapter_ok(actual, expected_chapter), (
                f"{query!r} resolved to {result.hsn_code} via {result.match_method} "
                f"(confidence={result.confidence:.2f}), expected chapter {expected_chapter}"
            )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_hsn_chapter_accuracy())
