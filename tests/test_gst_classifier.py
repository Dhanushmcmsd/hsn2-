"""Full test suite for the GST/HSN classifier.

Tests key tiers with known-good product cases.

Pass criteria (CBIC GST 2024-25):
  - Correct HSN code (exact 8-digit match)
  - Correct GST rate
  - Confidence ≥ 70% for Tiers 1-4
  - tier_used in expected range
  - needs_manual_review = False for Tiers 1-4
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Test cases — Source: CBIC HSN Master 2024-25
# ---------------------------------------------------------------------------

TEST_CASES = [
    # Health drinks (HSN 19019090, 18%)
    {"query": "BOOST",               "expected_hsn": "19019090", "expected_gst": 18.0, "category": "Health Drinks"},
    {"query": "HORLICKS",            "expected_hsn": "19019090", "expected_gst": 18.0, "category": "Health Drinks"},
    {"query": "COMPLAN",             "expected_hsn": "19019090", "expected_gst": 18.0, "category": "Health Drinks"},
    {"query": "BOURNVITA",           "expected_hsn": "19019090", "expected_gst": 18.0, "category": "Health Drinks"},
    # Noodles (HSN 19023000, 12%)
    {"query": "MAGGI",               "expected_hsn": "19023000", "expected_gst": 12.0, "category": "Noodles"},
    # Biscuits (HSN 19053100, 18%)
    {"query": "PARLE-G",             "expected_hsn": "19053100", "expected_gst": 18.0, "category": "Biscuits"},
    {"query": "BRITANNIA GOOD DAY",  "expected_hsn": "19053100", "expected_gst": 18.0, "category": "Biscuits"},
    # Chips (HSN 20052000, 12%)
    {"query": "LAYS",                "expected_hsn": "20052000", "expected_gst": 12.0, "category": "Chips"},
    # Personal care
    {"query": "COLGATE",             "expected_hsn": "33061000", "expected_gst": 18.0, "category": "Toothpaste"},
    {"query": "DETTOL SOAP",         "expected_hsn": "34011100", "expected_gst": 18.0, "category": "Soap"},
    {"query": "HEAD AND SHOULDERS",  "expected_hsn": "33051000", "expected_gst": 18.0, "category": "Shampoo"},
    {"query": "HEAD & SHOULDERS",    "expected_hsn": "33051000", "expected_gst": 18.0, "category": "Shampoo"},
    # Electronics
    {"query": "IPHONE",              "expected_hsn": "85171200", "expected_gst": 18.0, "category": "Mobile"},
    {"query": "SAMSUNG TV",          "expected_hsn": "85287200", "expected_gst": 28.0, "category": "TV"},
    {"query": "MACBOOK",             "expected_hsn": "84713000", "expected_gst": 18.0, "category": "Laptop"},
    # Pharma
    {"query": "DOLO 650",            "expected_hsn": "30049011", "expected_gst": 12.0, "category": "Medicine"},
    {"query": "CROCIN",              "expected_hsn": "30049011", "expected_gst": 12.0, "category": "Medicine"},
    # Beverages
    {"query": "COCA COLA",           "expected_hsn": "22021010", "expected_gst": 28.0, "category": "Soft Drink"},
    {"query": "BISLERI",             "expected_hsn": "22011000", "expected_gst": 18.0, "category": "Water"},
    # Detergent
    {"query": "SURF EXCEL",          "expected_hsn": "34022000", "expected_gst": 18.0, "category": "Detergent"},
]


# ---------------------------------------------------------------------------
# Unit tests for HSN validator
# ---------------------------------------------------------------------------

class TestHsnValidator:
    def test_valid_8_digit_hsn(self):
        from app.services.hsn_validator import validate_hsn_code
        result = validate_hsn_code("19019090")
        assert result.is_valid
        assert result.chapter == "19"
        assert result.heading == "1901"
        assert len(result.errors) == 0

    def test_valid_4_digit_sac(self):
        from app.services.hsn_validator import validate_hsn_code
        result = validate_hsn_code("9954")
        assert result.is_valid
        assert result.chapter == "99"

    def test_invalid_3_digit(self):
        from app.services.hsn_validator import validate_hsn_code
        result = validate_hsn_code("190")
        assert not result.is_valid
        assert any("length" in e.lower() for e in result.errors)

    def test_deprecated_hsn(self):
        from app.services.hsn_validator import validate_hsn_code
        result = validate_hsn_code("99999999")
        assert not result.is_valid
        assert any("placeholder" in e.lower() for e in result.errors)

    def test_amended_hsn_warning(self):
        from app.services.hsn_validator import validate_hsn_code
        result = validate_hsn_code("21069099")
        assert len(result.warnings) > 0
        assert "19019090" in result.warnings[0]

    def test_empty_hsn(self):
        from app.services.hsn_validator import validate_hsn_code
        result = validate_hsn_code("")
        assert not result.is_valid


class TestGstRateValidator:
    def test_valid_rates(self):
        from app.services.hsn_validator import validate_gst_rate
        for rate in [0.0, 0.1, 0.25, 1.5, 3.0, 5.0, 12.0, 18.0, 28.0]:
            result = validate_gst_rate(rate)
            assert result["is_valid"], f"Rate {rate} should be valid"

    def test_invalid_rate_15(self):
        from app.services.hsn_validator import validate_gst_rate
        result = validate_gst_rate(15.0)
        assert not result["is_valid"]
        assert len(result["errors"]) > 0

    def test_none_rate(self):
        from app.services.hsn_validator import validate_gst_rate
        result = validate_gst_rate(None)
        assert not result["is_valid"]

    def test_cess_warning_chapter22(self):
        from app.services.hsn_validator import validate_gst_rate
        result = validate_gst_rate(28.0, "22021010")
        assert result.get("cess_likely_applicable", False)


class TestValidateHsnGstPair:
    def test_valid_boost_hsn(self):
        from app.services.hsn_validator import validate_hsn_gst_pair
        result = validate_hsn_gst_pair("19019090", 18.0)
        assert result["is_valid"]
        assert len(result["errors"]) == 0

    def test_invalid_rate_for_biscuits(self):
        from app.services.hsn_validator import validate_hsn_gst_pair
        result = validate_hsn_gst_pair("19053100", 15.0)  # 15% is not valid
        assert not result["is_valid"]

    def test_valid_paracetamol(self):
        from app.services.hsn_validator import validate_hsn_gst_pair
        result = validate_hsn_gst_pair("30049011", 12.0)
        assert result["is_valid"]


# ---------------------------------------------------------------------------
# Unit tests for normalise_query in gst_classifier
# ---------------------------------------------------------------------------

class TestNormalizeQuery:
    def test_lowercase_to_upper(self):
        from app.services.gst_classifier import _normalize_query
        assert _normalize_query("boost") == "BOOST"

    def test_extra_spaces_collapsed(self):
        from app.services.gst_classifier import _normalize_query
        assert _normalize_query("  HORLICKS   JUNIOR ") == "HORLICKS JUNIOR"

    def test_special_chars_preserved(self):
        from app.services.gst_classifier import _normalize_query
        assert _normalize_query("parle-g") == "PARLE-G"


class TestIsValidHsn:
    def test_8_digit_valid(self):
        from app.services.gst_classifier import _is_valid_hsn
        assert _is_valid_hsn("19019090")

    def test_4_digit_valid(self):
        from app.services.gst_classifier import _is_valid_hsn
        assert _is_valid_hsn("1901")

    def test_2_digit_valid(self):
        from app.services.gst_classifier import _is_valid_hsn
        assert _is_valid_hsn("19")

    def test_3_digit_invalid(self):
        from app.services.gst_classifier import _is_valid_hsn
        assert not _is_valid_hsn("190")

    def test_empty_invalid(self):
        from app.services.gst_classifier import _is_valid_hsn
        assert not _is_valid_hsn("")


# ---------------------------------------------------------------------------
# Integration-style tests with mocked DB (Tier 1 — brand_aliases table)
# ---------------------------------------------------------------------------

class TestTier1ExactBrand:
    @pytest.mark.asyncio
    async def test_boost_returns_19019090(self):
        from app.services.gst_classifier import _tier1_exact_brand

        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "hsn_code": "19019090",
            "category": "Health Drinks",
            "gst_rate": 18.0,
            "cess_applicable": False,
            "verified_source": "CBIC HSN 2024-25",
            "brand_name": "BOOST",
            "description": "Malted milk food preparations",
        }[key]

        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = mock_row

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _tier1_exact_brand(mock_db, "BOOST")
        assert result is not None
        assert result["hsn_code"] == "19019090"
        assert result["gst_rate"] == 18.0
        assert result["confidence"] == 99
        assert result["tier_used"] == 1
        assert result["verified"] is True

    @pytest.mark.asyncio
    async def test_returns_none_on_db_error(self):
        from app.services.gst_classifier import _tier1_exact_brand

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("DB connection error"))

        result = await _tier1_exact_brand(mock_db, "BOOST")
        assert result is None


class TestTier2ExactProduct:
    @pytest.mark.asyncio
    async def test_exact_product_match(self):
        from app.services.gst_classifier import _tier2_exact_product

        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "hsn_code": "19023000",
            "description": "MAGGI 2 MINUTE NOODLES MASALA",
            "gst_rate": "12%",
            "hsn_description": "Other pasta, cooked or otherwise prepared",
            "hsn_gst_rate": 12.0,
        }[key]
        mock_row.get = lambda key, default=None: {
            "hsn_gst_rate": 12.0,
        }.get(key, default)

        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = mock_row

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _tier2_exact_product(mock_db, "MAGGI 2 MINUTE NOODLES MASALA")
        assert result is not None
        assert result["hsn_code"] == "19023000"
        assert result["gst_rate"] == 12.0
        assert result["confidence"] == 99
        assert result["tier_used"] == 2


class TestMakeResult:
    def test_make_result_structure(self):
        from app.services.gst_classifier import _make_result
        result = _make_result(
            "19019090", "Malted milk", 18.0, False, 99, 1,
            "brand_alias_exact", True, 5.0
        )
        assert result["hsn_code"] == "19019090"
        assert result["gst_rate"] == 18.0
        assert result["cess_applicable"] is False
        assert result["confidence"] == 99
        assert result["tier_used"] == 1
        assert result["verified"] is True
        assert result["elapsed_ms"] == 5.0
        assert result["needs_manual_review"] is False

    def test_manual_review_flag(self):
        from app.services.gst_classifier import _make_result
        result = _make_result(
            "UNCLASSIFIED", "Pending", None, False, 10, 6,
            "manual_review_queue", False, 2000.0, needs_manual_review=True
        )
        assert result["needs_manual_review"] is True
        assert result["confidence"] == 10


# ---------------------------------------------------------------------------
# Integration tests for classify endpoint via FastAPI test client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_endpoint_returns_result(client, api_key):
    """POST /api/v1/classify should return a valid classification response."""
    with patch("app.services.gst_classifier._tier1_exact_brand") as mock_t1, \
         patch("app.services.gst_classifier._tier0_cache", return_value=None):
        mock_t1.return_value = {
            "hsn_code": "19019090",
            "description": "Malted milk food preparations",
            "gst_rate": 18.0,
            "cess_applicable": False,
            "confidence": 99,
            "tier_used": 1,
            "source": "brand_alias_exact",
            "verified": True,
        }

        resp = await client.post(
            "/api/v1/classify",
            json={"query": "BOOST"},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hsn_code"] == "19019090"
        assert data["gst_rate"] == 18.0
        assert data["confidence"] == 99
        assert data["tier_used"] == 1


@pytest.mark.asyncio
async def test_classify_empty_query_rejected(client, api_key):
    """Empty query should be rejected with 422."""
    resp = await client.post(
        "/api/v1/classify",
        json={"query": ""},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_classify_batch_endpoint(client, api_key):
    """POST /api/v1/classify/batch should handle multiple queries."""
    with patch("app.services.gst_classifier.classify", new_callable=AsyncMock) as mock_classify:
        mock_classify.return_value = {
            "hsn_code": "19019090",
            "description": "Malted milk food preparations",
            "gst_rate": 18.0,
            "cess_applicable": False,
            "confidence": 99,
            "tier_used": 1,
            "source": "brand_alias_exact",
            "verified": True,
            "last_updated": "2024-03-15",
            "elapsed_ms": 3.0,
            "needs_manual_review": False,
        }

        resp = await client.post(
            "/api/v1/classify/batch",
            json={"queries": ["BOOST", "COLGATE", "MAGGI"]},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert "BOOST" in data["results"]


@pytest.mark.asyncio
async def test_compliance_validate_endpoint(client, api_key):
    """POST /api/v1/compliance/validate should validate HSN/GST pair."""
    resp = await client.post(
        "/api/v1/compliance/validate",
        json={"hsn_code": "19019090", "gst_rate": 18.0},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is True
    assert data["chapter"] == "19"
    assert len(data["errors"]) == 0


@pytest.mark.asyncio
async def test_compliance_validate_invalid_hsn(client, api_key):
    """Invalid HSN should return is_valid = False with errors."""
    resp = await client.post(
        "/api/v1/compliance/validate",
        json={"hsn_code": "99999999", "gst_rate": 18.0},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is False
    assert len(data["errors"]) > 0


@pytest.mark.asyncio
async def test_compliance_validate_invalid_gst_rate(client, api_key):
    """Invalid GST rate (15%) should fail validation."""
    resp = await client.post(
        "/api/v1/compliance/validate",
        json={"hsn_code": "19019090", "gst_rate": 15.0},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is False


@pytest.mark.asyncio
async def test_pending_reviews_requires_admin(client, api_key):
    """GET /api/v1/classify/pending should require admin key."""
    resp = await client.get(
        "/api/v1/classify/pending",
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_compliance_stats_requires_admin(client, api_key):
    """GET /api/v1/compliance/stats should require admin key."""
    resp = await client.get(
        "/api/v1/compliance/stats",
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Parametrized product test (all 20 known-good cases via validator)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", TEST_CASES, ids=[c["query"] for c in TEST_CASES])
def test_validator_accepts_known_good_hsn(case):
    """Every known-good product's expected HSN should pass CBIC validation."""
    from app.services.hsn_validator import validate_hsn_gst_pair
    result = validate_hsn_gst_pair(case["expected_hsn"], case["expected_gst"])
    assert result["is_valid"], (
        f"Expected HSN {case['expected_hsn']} / GST {case['expected_gst']}% "
        f"for {case['query']} to pass validation. Errors: {result['errors']}"
    )


@pytest.mark.parametrize("case", TEST_CASES, ids=[c["query"] for c in TEST_CASES])
def test_no_query_normalises_to_empty(case):
    """Normalized query should be non-empty for all known products."""
    from app.services.gst_classifier import _normalize_query
    norm = _normalize_query(case["query"])
    assert len(norm) > 0, f"Query '{case['query']}' normalized to empty string"


@pytest.mark.parametrize("rate", [0.0, 0.1, 0.25, 1.5, 3.0, 5.0, 12.0, 18.0, 28.0])
def test_all_valid_gst_rates_pass(rate):
    """All 9 valid Indian GST rates must pass the validator."""
    from app.services.hsn_validator import validate_gst_rate
    result = validate_gst_rate(rate)
    assert result["is_valid"], f"Rate {rate}% should be valid"


@pytest.mark.parametrize("rate", [4.0, 6.0, 7.0, 9.0, 10.0, 11.0, 14.0, 15.0, 16.0, 20.0, 24.0, 26.0])
def test_invalid_gst_rates_fail(rate):
    """Non-standard GST rates must fail validation."""
    from app.services.hsn_validator import validate_gst_rate
    result = validate_gst_rate(rate)
    assert not result["is_valid"], f"Rate {rate}% should be INVALID in India"
