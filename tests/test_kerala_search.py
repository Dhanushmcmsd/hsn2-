import asyncio
import os

import pytest

from app.services.kerala_search import (
    expand_kerala_query,
    kerala_fallback_search,
    parse_vkc_code,
)
from tests.legacy_main import get_match_one, has_live_postgres_url, normalize_asyncpg_url


KERALA_SEARCH_CASES = [
    ("CAMLIN SMALL SC MR NOTE BOOK 80P", "48"),
    ("VKC FTGR DB19109 MAR.BG.LAD 04", "64"),
    ("AJMI STEAM MADE PUTTUPODI 1KG", "11"),
    ("AVAL WHITE REGULAR 500G", "19"),
    ("CB MATTA BROKEN RICE NICE 500G", "10"),
    ("OM SHANTHI JASMNE PURE PUJA OIL 1000ml", "15"),
    ("BRAHMINS FRIED RAVA 1KG", "19"),
    ("EASTERN TURMERIC POWDER 100G", "09"),
    ("KITCHEN TR.CHILLI POWDER 100G", "09"),
    ("MILMA GHEE BTL 50ml", "04"),
    ("REAL1 KOZHUVA ROAST 100G", "03"),
    ("TRIPTI NADAN UNNIYAPPAM 180G", "19"),
    ("DOUBLE HORSE PALADA PAYASAM MIX 300G", "19"),
    ("PAVITHRAM TAMARIND 100G", "08"),
    ("K.P.NAM.PATHIMUGHAM 15g", "12"),
    ("BODHINI APPAM IDIAPPAM PODI 1KG", "11"),
    ("HORLICKS WOMENS CHOCO PET 400G", "21"),
    ("HARPIC DISINFTNT BTRM CLNR FLORL 500ML", "34"),
]


def test_expand_kerala_query_expands_invoice_shorthand():
    expanded = expand_kerala_query("CAMLIN SMALL SC MR NOTE BOOK 80P")
    assert "SCHOOL SPIRAL CLOSED" in expanded
    assert "MARGIN RULED" in expanded


def test_parse_vkc_code_maps_to_footwear():
    result = parse_vkc_code("VKC FTGR DB19109 MAR.BG.LAD 04")
    assert result is not None
    assert result["hsn_code"] == "64022090"
    assert result["score"] == pytest.approx(0.87)


@pytest.mark.asyncio
async def test_kerala_alias_exact_without_db_round_trip():
    results = await kerala_fallback_search("PUJA OIL", None)  # type: ignore[arg-type]
    assert results
    assert results[0]["hsn_code"] == "15180040"
    assert results[0]["method"] == "kerala_alias_exact"


@pytest.mark.skipif(
    not has_live_postgres_url(),
    reason="Postgres DATABASE_URL required for live Kerala matcher verification",
)
@pytest.mark.asyncio
async def test_kerala_search_cases_resolve_to_expected_chapters():
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
        for query, expected_chapter in KERALA_SEARCH_CASES:
            result = await _match_one(query, db)
            assert result.hsn_code, f"{query!r} returned no HSN result"
            assert result.hsn_code[:2] == expected_chapter, (
                f"{query!r} resolved to {result.hsn_code} via {result.match_method} "
                f"(confidence={result.confidence:.2f}), expected chapter {expected_chapter}"
            )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_kerala_search_cases_resolve_to_expected_chapters())
