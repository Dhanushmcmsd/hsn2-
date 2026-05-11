"""tests/test_gst_fetcher_cbic_fallback.py

Tests for CBIC scrape failure alerting in fetch_all_gst_rates().
Covers:
  1. CBIC failure → logger.error fired, CSV fallback returned
  2. CBIC success → logger.error NOT fired
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_CSV_RATES = {
    "01011000": {"rate": 0.0, "effective_from": date(2017, 7, 1), "source": "csv-fallback"},
    "01012100": {"rate": 12.0, "effective_from": date(2017, 7, 1), "source": "csv-fallback"},
}

_FAKE_CBIC_RATES = {
    "01011000": {"rate": 0.0, "effective_from": date(2017, 7, 1), "source": "cbic"},
    "01012100": {"rate": 12.0, "effective_from": date(2017, 7, 1), "source": "cbic"},
}


# ---------------------------------------------------------------------------
# Test 1 — CBIC fails → logger.error is called, CSV fallback returned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cbic_fail_logs_error():
    """When _fetch_from_cbic raises, fetch_all_gst_rates must:
    - call logger.error with a message containing 'CBIC scrape FAILED'
    - return the CSV fallback (non-empty dict)
    """
    with (
        patch(
            "app.services.gst_fetcher._cache_get",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.gst_fetcher._fetch_from_cbic",
            new_callable=AsyncMock,
            side_effect=Exception("timeout"),
        ),
        patch(
            "app.services.gst_fetcher._load_from_csv",
            return_value=_FAKE_CSV_RATES,
        ),
        patch(
            "app.services.gst_fetcher._cache_set",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.gst_fetcher.logger"
        ) as mock_logger,
        patch(
            "app.services.gst_fetcher.log"
        ) as mock_structlog,
        patch(
            "app.utils.metrics.gst_cbic_scrape_failures_total"
        ) as mock_counter,
    ):
        # Wire the Prometheus label mock
        mock_counter.labels.return_value = MagicMock()

        from app.services.gst_fetcher import fetch_all_gst_rates

        result = await fetch_all_gst_rates()

    # logger.error must contain the sentinel phrase
    error_calls = mock_logger.error.call_args_list
    assert error_calls, "Expected logger.error to be called at least once"
    combined_msg = " ".join(
        str(call.args[0]) for call in error_calls
    )
    assert "CBIC scrape FAILED" in combined_msg, (
        f"Expected 'CBIC scrape FAILED' in logger.error message, got: {combined_msg!r}"
    )

    # structlog event must be emitted
    mock_structlog.error.assert_called_once()
    structlog_event = mock_structlog.error.call_args.args[0]
    assert structlog_event == "gst_fetcher.cbic_scrape_failed_using_fallback"

    # Prometheus counter incremented
    mock_counter.labels.assert_called_once_with(fallback_source="csv")
    mock_counter.labels.return_value.inc.assert_called_once()

    # Return value is non-empty (CSV data)
    assert result, "Expected non-empty dict from CSV fallback"


# ---------------------------------------------------------------------------
# Test 2 — CBIC succeeds → logger.error is NOT called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cbic_success_no_alert():
    """When _fetch_from_cbic succeeds, logger.error must NOT be called."""
    with (
        patch(
            "app.services.gst_fetcher._cache_get",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.gst_fetcher._fetch_from_cbic",
            new_callable=AsyncMock,
            return_value=_FAKE_CBIC_RATES,
        ),
        patch(
            "app.services.gst_fetcher._cache_set",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.gst_fetcher.logger"
        ) as mock_logger,
        patch(
            "app.services.gst_fetcher.log"
        ) as mock_structlog,
    ):
        from app.services.gst_fetcher import fetch_all_gst_rates

        result = await fetch_all_gst_rates()

    # No errors should fire
    mock_logger.error.assert_not_called()
    mock_structlog.error.assert_not_called()

    # Result is the live CBIC data
    assert result == _FAKE_CBIC_RATES
