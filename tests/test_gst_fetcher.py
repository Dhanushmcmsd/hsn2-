"""
tests/test_gst_fetcher.py
=========================
Unit tests for app/services/gst_fetcher.py.

Covers:
  1. Layer 1 (CBIC scrape) happy path
  2. Layer 1 failure → CSV fallback  (layer 2 is skipped in bulk fetch)
  3. All layers fail → CSV fallback with WARNING log
  4. Redis cache hit → no HTTP calls

Dependencies: pytest, pytest-asyncio, respx, httpx
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx


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

_CBIC_URL  = "https://cbic-gst.gov.in/gst-goods-services-rates.html"
_GST_URL   = "https://services.gst.gov.in/services/searchhsnsac"

_MOCK_CSV_RATES = {
    "0101": {"rate": 5.0, "effective_from": date(2017, 7, 1), "source": "csv-fallback"},
    "1001": {"rate": 12.0, "effective_from": date(2017, 7, 1), "source": "csv-fallback"},
}


# ---------------------------------------------------------------------------
# Test 1 — Layer 1 CBIC scrape success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layer1_cbic_scraper_success():
    """Mock CBIC returning valid HTML; assert correct rates and source."""
    # Disable Redis so we don't need a live server
    with patch("app.services.gst_fetcher._cache_get", new_callable=AsyncMock, return_value=None), \
         patch("app.services.gst_fetcher._cache_set", new_callable=AsyncMock):

        with respx.mock(assert_all_called=False) as mock_http:
            mock_http.get(_CBIC_URL).mock(
                return_value=httpx.Response(200, text=_VALID_CBIC_HTML)
            )

            from app.services.gst_fetcher import fetch_all_gst_rates
            result = await fetch_all_gst_rates()

    assert "0101" in result, "Expected HSN 0101 in result"
    assert "1001" in result, "Expected HSN 1001 in result"
    assert result["0101"]["rate"] == pytest.approx(5.0)
    assert result["1001"]["rate"] == pytest.approx(12.0)
    assert result["2201"]["rate"] == pytest.approx(18.0)
    # All sourced from cbic scrape
    assert all(v["source"] == "cbic" for v in result.values())


# ---------------------------------------------------------------------------
# Test 2 — Layer 1 fails → falls through to CSV fallback
#          (Layer 2 bulk is intentionally skipped in fetch_all_gst_rates)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_layer1_fails_fallback_to_csv():
    """
    CBIC returns 500 → Layer 1 raises → CSV fallback is used.
    (The bulk fetch path skips Layer 2 by design; see gst_fetcher.py comments.)
    """
    with patch("app.services.gst_fetcher._cache_get", new_callable=AsyncMock, return_value=None), \
         patch("app.services.gst_fetcher._cache_set", new_callable=AsyncMock), \
         patch("app.services.gst_fetcher._load_from_csv", return_value=_MOCK_CSV_RATES) as mock_csv:

        with respx.mock(assert_all_called=False) as mock_http:
            mock_http.get(_CBIC_URL).mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )

            from app.services import gst_fetcher
            import importlib
            importlib.reload(gst_fetcher)  # clear any cached module-level state
            result = await gst_fetcher.fetch_all_gst_rates()

    mock_csv.assert_called_once()
    assert result is _MOCK_CSV_RATES or set(result.keys()) == set(_MOCK_CSV_RATES.keys())


# ---------------------------------------------------------------------------
# Test 3 — All layers fail → CSV fallback + WARNING logged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_layers_fail_returns_csv_fallback(caplog):
    """
    Both CBIC and the in-flight httpx client raise ConnectError.
    Assert source == 'csv-fallback' and a WARNING was emitted.
    """
    import logging

    with patch("app.services.gst_fetcher._cache_get", new_callable=AsyncMock, return_value=None), \
         patch("app.services.gst_fetcher._cache_set", new_callable=AsyncMock), \
         patch("app.services.gst_fetcher._load_from_csv", return_value=_MOCK_CSV_RATES):

        with respx.mock(assert_all_called=False) as mock_http:
            mock_http.get(_CBIC_URL).mock(
                side_effect=httpx.ConnectError("connection refused")
            )

            with caplog.at_level(logging.WARNING, logger="app.services.gst_fetcher"):
                from app.services import gst_fetcher
                import importlib
                importlib.reload(gst_fetcher)
                result = await gst_fetcher.fetch_all_gst_rates()

    # The CSV fallback always emits a WARNING
    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("fallback" in str(m).lower() or "layer" in str(m).lower()
               for m in warning_messages), \
        f"Expected a WARNING log about fallback. Got: {warning_messages}"

    assert len(result) > 0, "CSV fallback should return non-empty dict"
    sources = {v["source"] for v in result.values()}
    assert "csv-fallback" in sources


# ---------------------------------------------------------------------------
# Test 4 — Redis cache hit → zero HTTP calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redis_cache_hit_skips_http():
    """
    Pre-populate the mock Redis cache.
    Assert that no HTTP calls are made to CBIC or gst.gov.in.
    """
    cached_payload = {
        "0101": {"rate": 5.0, "effective_from": "2017-07-01", "source": "cache"},
        "9999": {"rate": 28.0, "effective_from": "2020-01-01", "source": "cache"},
    }

    with patch(
        "app.services.gst_fetcher._cache_get",
        new_callable=AsyncMock,
        return_value=cached_payload,
    ):
        # All HTTP must remain uncalled
        with respx.mock(assert_all_called=False) as mock_http:
            from app.services import gst_fetcher
            import importlib
            importlib.reload(gst_fetcher)
            result = await gst_fetcher.fetch_all_gst_rates()

        assert not mock_http.calls, "No HTTP requests should be made on cache hit"

    assert "0101" in result
    assert result["0101"]["rate"] == pytest.approx(5.0)
    assert result["9999"]["rate"] == pytest.approx(28.0)
    # Source is preserved from cache
    assert result["0101"]["source"] == "cache"
