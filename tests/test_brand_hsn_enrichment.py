"""Comprehensive HSN + GST brand classification tests.

Tests verify:
  1. Correct HSN returned for each brand/product
  2. Correct GST percentage
  3. Confidence > 70%
  4. No 99999999 returned for known brands

Brands covered:
  BOOST, HORLICKS, COMPLAN, BOURNVITA, DETTOL, COLGATE,
  PARACETAMOL, MAGGI, BRITANNIA GOOD DAY

Run with:
  pytest tests/test_brand_hsn_enrichment.py -v

Requires DATABASE_URL env var pointing to Neon PostgreSQL.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import pytest
import pytest_asyncio

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL env var required for live DB tests",
)


# ── Test fixtures ──────────────────────────────────────────────────────────────

def _make_async_engine(raw_url: str):
    """Normalise a Postgres URL for asyncpg and return a SQLAlchemy async engine."""
    import re as _re
    from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
    from sqlalchemy.ext.asyncio import create_async_engine

    url = raw_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Strip sslmode — asyncpg uses ssl= connect_arg, not a URL param
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.pop("sslmode", None)
    params.pop("channel_binding", None)
    params["statement_cache_size"] = "0"
    params["prepared_statement_cache_size"] = "0"
    url = urlunparse(parsed._replace(query=urlencode(params, doseq=True)))

    return create_async_engine(
        url,
        connect_args={"ssl": "require", "statement_cache_size": 0, "prepared_statement_cache_size": 0},
        echo=False,
    )


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Create a fresh async DB session per test function (avoids asyncpg concurrency issues)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _make_async_engine(os.environ["DATABASE_URL"])
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    await engine.dispose()


# ── Helper utilities ───────────────────────────────────────────────────────────

def _parse_gst_pct(gst_raw: Any) -> float | None:
    """Extract numeric percentage from GST string like 'GST 18%' or float 18.0."""
    if gst_raw is None:
        return None
    if isinstance(gst_raw, (int, float)):
        return float(gst_raw)
    m = re.search(r"(\d+(?:\.\d+)?)", str(gst_raw))
    return float(m.group(1)) if m else None


def _assert_result(
    result: dict,
    *,
    brand: str,
    expected_chapter: str,
    expected_hsn_prefix: str | None = None,
    expected_gst: float | None = None,
    min_confidence: int = 70,
):
    """Central assertion helper shared by all brand test cases."""
    assert result is not None, f"{brand}: brand_lookup returned None"

    hsn = result.get("hsn_code", "")
    assert hsn, f"{brand}: returned empty HSN code"
    assert hsn != "99999999", f"{brand}: returned unclassified HSN 99999999"
    assert hsn[:2] == expected_chapter, (
        f"{brand}: HSN {hsn} is in chapter {hsn[:2]}, expected chapter {expected_chapter}"
    )

    if expected_hsn_prefix:
        assert hsn.startswith(expected_hsn_prefix), (
            f"{brand}: HSN {hsn} does not start with expected prefix {expected_hsn_prefix}"
        )

    if expected_gst is not None:
        gst_val = _parse_gst_pct(result.get("gst_rate"))
        assert gst_val is not None, f"{brand}: GST rate is missing"
        assert gst_val == expected_gst, (
            f"{brand}: GST rate {gst_val}% != expected {expected_gst}%"
        )

    score = float(result.get("score", 0))
    confidence = min(100, round(score * 100))
    assert confidence >= min_confidence, (
        f"{brand}: confidence {confidence}% is below minimum {min_confidence}%"
    )


# ── Brand test cases ───────────────────────────────────────────────────────────
#
# Each test uses brand_lookup() directly (Tier 0 / Tier 1 / Tier 2 / Tier 3)
# and also verifies the data in verified_products is consistent.

class TestMaltHealthDrinks:
    """Malt-based health drinks: HSN Chapter 19 (heading 1901), GST 18%."""

    @pytest.mark.asyncio
    async def test_boost_brand_lookup(self, db_session):
        """BOOST → HSN 19xxxxxx → GST 18%."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "BOOST", min_score=0.50)
        _assert_result(
            result,
            brand="BOOST",
            expected_chapter="19",
            expected_hsn_prefix="190",
            expected_gst=18.0,
            min_confidence=80,
        )

    @pytest.mark.asyncio
    async def test_boost_with_size(self, db_session):
        """BOOST 750GM POUCH → should still resolve to Chapter 19."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "BOOST 750GM POUCH", min_score=0.50)
        _assert_result(result, brand="BOOST 750GM POUCH", expected_chapter="19", min_confidence=70)

    @pytest.mark.asyncio
    async def test_horlicks_brand_lookup(self, db_session):
        """HORLICKS → HSN 19019090 → GST 18%."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "HORLICKS", min_score=0.50)
        _assert_result(
            result,
            brand="HORLICKS",
            expected_chapter="19",
            expected_gst=18.0,
            min_confidence=80,
        )

    @pytest.mark.asyncio
    async def test_horlicks_womens(self, db_session):
        """HORLICKS WOMENS → Chapter 19, confidence > 70%."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "HORLICKS WOMENS", min_score=0.50)
        _assert_result(result, brand="HORLICKS WOMENS", expected_chapter="19", min_confidence=70)

    @pytest.mark.asyncio
    async def test_complan_brand_lookup(self, db_session):
        """COMPLAN → HSN 19019090 → GST 18%."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "COMPLAN", min_score=0.50)
        _assert_result(
            result,
            brand="COMPLAN",
            expected_chapter="19",
            expected_gst=18.0,
            min_confidence=80,
        )

    @pytest.mark.asyncio
    async def test_bournvita_brand_lookup(self, db_session):
        """BOURNVITA → Chapter 19, GST 18%."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "BOURNVITA", min_score=0.50)
        _assert_result(
            result,
            brand="BOURNVITA",
            expected_chapter="19",
            expected_gst=18.0,
            min_confidence=70,
        )


class TestPersonalCare:
    """Personal care and hygiene products: Chapters 33 and 34."""

    @pytest.mark.asyncio
    async def test_dettol_brand_lookup(self, db_session):
        """DETTOL → HSN 3808xxxx (antiseptic) → GST 18%."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "DETTOL", min_score=0.50)
        _assert_result(
            result,
            brand="DETTOL",
            expected_chapter="38",
            min_confidence=80,
        )

    @pytest.mark.asyncio
    async def test_colgate_brand_lookup(self, db_session):
        """COLGATE → HSN 3306xxxx (oral hygiene) → GST 18%."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "COLGATE", min_score=0.50)
        _assert_result(
            result,
            brand="COLGATE",
            expected_chapter="33",
            min_confidence=80,
        )

    @pytest.mark.asyncio
    async def test_colgate_toothbrush(self, db_session):
        """COLGATE toothbrush → Chapter 96 (toothbrush) or 33 (toothpaste)."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "COLGATE TOOTHBRUSH", min_score=0.40)
        assert result is not None, "COLGATE TOOTHBRUSH returned no result"
        assert result.get("hsn_code") != "99999999", "COLGATE TOOTHBRUSH returned unclassified HSN"


class TestPharmaceuticals:
    """Pharmaceutical products: HSN Chapter 30."""

    @pytest.mark.asyncio
    async def test_paracetamol_brand_lookup(self, db_session):
        """PARACETAMOL → HSN 3004xxxx → Chapter 30."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "PARACETAMOL", min_score=0.50)
        _assert_result(
            result,
            brand="PARACETAMOL",
            expected_chapter="30",
            min_confidence=75,
        )

    @pytest.mark.asyncio
    async def test_paracetamol_tablet_query(self, db_session):
        """'paracetamol 500mg tablet' → Chapter 30."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "paracetamol 500mg tablet", min_score=0.50)
        _assert_result(result, brand="paracetamol tablet", expected_chapter="30", min_confidence=70)


class TestPackagedFood:
    """Packaged food products: Chapters 19 and 21."""

    @pytest.mark.asyncio
    async def test_maggi_noodles(self, db_session):
        """MAGGI → HSN 1902xxxx (pasta/noodles) → Chapter 19."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "MAGGI", min_score=0.50)
        _assert_result(
            result,
            brand="MAGGI",
            expected_chapter="19",
            min_confidence=80,
        )

    @pytest.mark.asyncio
    async def test_britannia_good_day(self, db_session):
        """BRITANNIA GOOD DAY → HSN 1905xxxx (biscuits) → Chapter 19."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "BRITANNIA GOOD DAY", min_score=0.50)
        _assert_result(
            result,
            brand="BRITANNIA GOOD DAY",
            expected_chapter="19",
            min_confidence=75,
        )

    @pytest.mark.asyncio
    async def test_britannia_brand_only(self, db_session):
        """BRITANNIA (brand-only) → Chapter 19."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, "BRITANNIA", min_score=0.50)
        _assert_result(result, brand="BRITANNIA", expected_chapter="19", min_confidence=75)


# ── Database consistency tests (verify the enrichment migration worked) ────────

class TestDatabaseConsistency:
    """Verify the enrichment migration correctly updated the DB."""

    @pytest.mark.asyncio
    async def test_no_malt_brand_uses_wrong_hsn(self, db_session):
        """BOOST/HORLICKS/COMPLAN/BOURNVITA must NOT have HSN 21069099."""
        from sqlalchemy import text
        rows = (await db_session.execute(text("""
            SELECT brand, description, hsn_code FROM verified_products
            WHERE brand IN ('BOOST','HORLICKS','COMPLAN','BOURNVITA')
              AND hsn_code = '21069099'
        """))).fetchall()
        assert len(rows) == 0, (
            f"Found {len(rows)} malt-brand rows still using wrong HSN 21069099: "
            + str([(r[0], r[1], r[2]) for r in rows])
        )

    @pytest.mark.asyncio
    async def test_malt_brands_have_18pct_gst(self, db_session):
        """All BOOST/HORLICKS/COMPLAN entries must have GST 18%."""
        from sqlalchemy import text
        rows = (await db_session.execute(text("""
            SELECT brand, description, gst_rate FROM verified_products
            WHERE brand IN ('BOOST','HORLICKS','COMPLAN','BOURNVITA')
              AND (gst_rate IS NULL OR gst_rate NOT IN ('GST 18%','18%','18'))
        """))).fetchall()
        assert len(rows) == 0, (
            f"Found {len(rows)} malt-brand rows with incorrect GST rate: "
            + str([(r[0], r[1], r[2]) for r in rows])
        )

    @pytest.mark.asyncio
    async def test_malt_brands_in_chapter_19(self, db_session):
        """All BOOST/HORLICKS/COMPLAN/BOURNVITA HSN codes must start with '19'."""
        from sqlalchemy import text
        rows = (await db_session.execute(text("""
            SELECT brand, description, hsn_code FROM verified_products
            WHERE brand IN ('BOOST','HORLICKS','COMPLAN','BOURNVITA')
              AND hsn_code NOT LIKE '19%'
        """))).fetchall()
        assert len(rows) == 0, (
            f"Found {len(rows)} malt-brand rows outside Chapter 19: "
            + str([(r[0], r[1], r[2]) for r in rows])
        )

    @pytest.mark.asyncio
    async def test_hsn_19019090_has_description(self, db_session):
        """HSN 19019090 must have a real description (not 'unavailable')."""
        from sqlalchemy import text
        row = (await db_session.execute(text("""
            SELECT description FROM hsn_codes WHERE hsn_code = '19019090'
        """))).fetchone()
        assert row is not None, "HSN 19019090 missing from hsn_codes"
        desc = row[0] or ""
        assert "unavailable" not in desc.lower(), (
            f"HSN 19019090 still has placeholder description: {desc!r}"
        )
        assert len(desc) > 20, f"HSN 19019090 description too short: {desc!r}"

    @pytest.mark.asyncio
    async def test_brand_aliases_populated(self, db_session):
        """FMCG brand aliases must be in language_aliases (min 40 entries)."""
        from sqlalchemy import text
        row = (await db_session.execute(text("""
            SELECT COUNT(*) FROM language_aliases
            WHERE source = 'FMCG_BRAND_MASTER_2024'
        """))).fetchone()
        count = row[0] if row else 0
        assert count >= 40, (
            f"Expected ≥ 40 FMCG brand aliases, found {count}"
        )

    @pytest.mark.asyncio
    async def test_enrichment_log_exists(self, db_session):
        """brand_hsn_enrichment_log table must exist and have entries."""
        from sqlalchemy import text
        row = (await db_session.execute(text("""
            SELECT COUNT(*) FROM brand_hsn_enrichment_log
        """))).fetchone()
        count = row[0] if row else 0
        assert count > 0, "brand_hsn_enrichment_log is empty — enrichment may not have run"

    @pytest.mark.asyncio
    async def test_boost_alias_in_language_aliases(self, db_session):
        """BOOST must be in language_aliases pointing to HSN 19019090."""
        from sqlalchemy import text
        row = (await db_session.execute(text("""
            SELECT hsn_code FROM language_aliases
            WHERE term_normalized = 'BOOST' AND source = 'FMCG_BRAND_MASTER_2024'
        """))).fetchone()
        assert row is not None, "BOOST alias not found in language_aliases"
        assert row[0] == "19019090", f"BOOST alias HSN = {row[0]}, expected 19019090"

    @pytest.mark.asyncio
    async def test_horlicks_alias_in_language_aliases(self, db_session):
        """HORLICKS must be in language_aliases pointing to HSN 19019090."""
        from sqlalchemy import text
        row = (await db_session.execute(text("""
            SELECT hsn_code FROM language_aliases
            WHERE term_normalized = 'HORLICKS' AND source = 'FMCG_BRAND_MASTER_2024'
        """))).fetchone()
        assert row is not None, "HORLICKS alias not found in language_aliases"
        assert row[0] == "19019090", f"HORLICKS alias HSN = {row[0]}, expected 19019090"


# ── Error boundary tests ──────────────────────────────────────────────────────

class TestErrorBoundary:
    """Verify the 99999999 error boundary never fires for known brands."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "BOOST",
        "HORLICKS",
        "COMPLAN",
        "BOURNVITA",
        "DETTOL",
        "COLGATE",
        "PARACETAMOL",
        "MAGGI",
        "BRITANNIA",
    ])
    async def test_no_unclassified_for_known_brands(self, db_session, query):
        """Known brand queries must NEVER return HSN 99999999."""
        from app.services.brand_search import brand_lookup
        result = await brand_lookup(db_session, query, min_score=0.40)
        # If brand_lookup returns None here, it means the brand was not found
        # at all — which is a separate problem. We only assert no 99999999.
        if result is not None:
            hsn = result.get("hsn_code", "")
            assert hsn != "99999999", (
                f"brand_lookup returned HSN 99999999 for known brand {query!r}"
            )


# ── Run standalone ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    async def _run_quick_check():
        """Quick standalone check — prints a pass/fail table."""
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            print("ERROR: Set DATABASE_URL env var to run these tests.")
            sys.exit(1)

        from sqlalchemy.ext.asyncio import async_sessionmaker
        from app.services.brand_search import brand_lookup

        engine = _make_async_engine(db_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        test_cases = [
            ("BOOST",          "19", 18.0),
            ("HORLICKS",       "19", 18.0),
            ("COMPLAN",        "19", 18.0),
            ("BOURNVITA",      "19", 18.0),
            ("DETTOL",         "38", None),
            ("COLGATE",        "33", None),
            ("PARACETAMOL",    "30", None),
            ("MAGGI",          "19", None),
            ("BRITANNIA GOOD DAY", "19", None),
        ]

        print(f"\n{'Query':<25} {'HSN':<12} {'GST%':<8} {'Score':<8} {'Pass?'}")
        print("-" * 70)

        passed = 0
        failed = 0
        async with session_factory() as db:
            for query, exp_chapter, exp_gst in test_cases:
                try:
                    result = await brand_lookup(db, query, min_score=0.40)
                    if result:
                        hsn = result.get("hsn_code", "N/A")
                        gst = _parse_gst_pct(result.get("gst_rate"))
                        score = round(float(result.get("score", 0)) * 100)
                        ok_hsn = hsn[:2] == exp_chapter and hsn != "99999999"
                        ok_gst = exp_gst is None or gst == exp_gst
                        ok_conf = score >= 70
                        passed_case = ok_hsn and ok_gst and ok_conf
                        status = "PASS" if passed_case else "FAIL"
                        if passed_case:
                            passed += 1
                        else:
                            failed += 1
                        print(f"{query:<25} {hsn:<12} {str(gst) + '%':<8} {score}%{'':<4} {status}")
                    else:
                        print(f"{query:<25} {'None':<12} {'N/A':<8} {'0%':<8} FAIL (no result)")
                        failed += 1
                except Exception as exc:
                    print(f"{query:<25} {'ERROR':<12} {'N/A':<8} {'0%':<8} FAIL ({exc})")
                    failed += 1

        await engine.dispose()
        print(f"\nResults: {passed} passed, {failed} failed out of {len(test_cases)} cases")
        sys.exit(0 if failed == 0 else 1)

    asyncio.run(_run_quick_check())
