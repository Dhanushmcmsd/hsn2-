"""
tests/test_gst_fetcher.py
=========================
Unit tests for app/services/gst_fetcher.py.

Covers:
  1. Layer 1 (CBIC scrape) happy path
  2. Layer 1 failure -> CSV fallback  (layer 2 is skipped in bulk fetch)
  3. All layers fail -> CSV fallback with WARNING log
  4. Redis cache hit -> no HTTP calls

Dependencies: pytest, pytest-asyncio, respx, httpx
"""
from __future__ import annotations

import logging
from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

# Import once at module level — never reload inside a patch context
import app.services.gst_fetcher as gst_fetcher_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_CBIC_HTML = """
<html><body>
<table>
  <tr><th>HSN Code</th><th>GST Rate %</th><th>Effective Date</th></tr>
  <tr><td>0101</td><td>5</td><td>01-07-2017</td></tr>
  <tr><td>1001</td><td>12</td><td>01-07-2017</td></tr>
  <tr><td>2201</td><td>18</td><td>01-01-2024</td></tr>
</table>
</body></html>
"""

_CBIC_URL = "https://cbic-gst.gov.in/gst-goods-services-rates.html"

_MOCK_CSV_RATES = {
    "0101": {"rate": 5.0,  "effective_from": date(2017, 7, 1), "source": "csv-fallback"},
    "1001": {"rate": 12.0, "effective_from": date(2017, 7, 1), "source": "csv-fallback"},
}


# ---------------------------------------------------------------------------
# Test 1 - Layer 1 CBIC scrape success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layer1_cbic_scraper_success():
    """Mock CBIC returning valid HTML; assert correct rates and source."""
    with patch.object(gst_fetcher_mod, "_cache_get", new_callable=AsyncMock, return_value=None), \
         patch.object(gst_fetcher_mod, "_cache_set", new_callable=AsyncMock):

        with respx.mock(assert_all_called=False) as mock_http:
            mock_http.get(_CBIC_URL).mock(
                return_value=httpx.Response(200, text=_VALID_CBIC_HTML)
            )
            result = await gst_fetcher_mod.fetch_all_gst_rates()

    assert "0101" in result
    assert "1001" in result
    assert result["0101"]["rate"] == pytest.approx(5.0)
    assert result["1001"]["rate"] == pytest.approx(12.0)
    assert result["2201"]["rate"] == pytest.approx(18.0)
    assert all(v["source"] == "cbic" for v in result.values())


# ---------------------------------------------------------------------------
# Test 2 - Layer 1 fails -> CSV fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layer1_fails_fallback_to_csv():
    """
    CBIC returns 500 -> Layer 1 raises -> CSV fallback is used.
    Layer 2 bulk is intentionally skipped (see gst_fetcher.py comments).
    """
    with patch.object(gst_fetcher_mod, "_cache_get", new_callable=AsyncMock, return_value=None), \
         patch.object(gst_fetcher_mod, "_cache_set", new_callable=AsyncMock), \
         patch.object(gst_fetcher_mod, "_load_from_csv", return_value=_MOCK_CSV_RATES) as mock_csv:

        with respx.mock(assert_all_called=False):
            respx.get(_CBIC_URL).mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )
            result = await gst_fetcher_mod.fetch_all_gst_rates()

    mock_csv.assert_called_once()
    assert set(result.keys()) == set(_MOCK_CSV_RATES.keys())


# ---------------------------------------------------------------------------
# Test 3 - All layers fail -> CSV fallback + WARNING logged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_layers_fail_returns_csv_fallback(caplog):
    """
    CBIC raises ConnectError -> falls to CSV fallback.
    Assert a WARNING was emitted and source == 'csv-fallback'.
    """
    with patch.object(gst_fetcher_mod, "_cache_get", new_callable=AsyncMock, return_value=None), \
         patch.object(gst_fetcher_mod, "_cache_set", new_callable=AsyncMock), \
         patch.object(gst_fetcher_mod, "_load_from_csv", return_value=_MOCK_CSV_RATES):

        with respx.mock(assert_all_called=False):
            respx.get(_CBIC_URL).mock(side_effect=httpx.ConnectError("connection refused"))

            with caplog.at_level(logging.WARNING, logger="app.services.gst_fetcher"):
                result = await gst_fetcher_mod.fetch_all_gst_rates()

    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        "fallback" in str(m).lower() or "layer" in str(m).lower()
        for m in warning_messages
    ), f"Expected a WARNING about fallback. Got: {warning_messages}"

    assert len(result) > 0, "CSV fallback should return non-empty dict"
    assert all(v["source"] == "csv-fallback" for v in result.values())


# ---------------------------------------------------------------------------
# Test 4 - Redis cache hit -> zero HTTP calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redis_cache_hit_skips_http():
    """
    _cache_get returns pre-built data -> no HTTP calls should be made.
    """
    cached_payload = {
        "0101": {"rate": 5.0,  "effective_from": "2017-07-01", "source": "cache"},
        "9999": {"rate": 28.0, "effective_from": "2020-01-01", "source": "cache"},
    }

    # respx.mock wraps OUTSIDE the patch so any accidental HTTP call raises
    with respx.mock(assert_all_called=False) as mock_http:
        with patch.object(
            gst_fetcher_mod,
            "_cache_get",
            new_callable=AsyncMock,
            return_value=cached_payload,
        ):
            result = await gst_fetcher_mod.fetch_all_gst_rates()

    assert not mock_http.calls, "No HTTP requests should be made on a cache hit"
    assert "0101" in result
    assert result["0101"]["rate"] == pytest.approx(5.0)
    assert result["9999"]["rate"] == pytest.approx(28.0)
    assert result["0101"]["source"] == "cache"
