"""tests/test_bulk_cache_gst_fallback.py

Unit tests for Fix 4 — Bulk cache missing GST fields.

Covers three scenarios in predict_bulk():
  1. Cache hit where gst_rate is already populated → no fallback called
  2. Cache hit where gst_rate is None (pre-GST entry) → fallback called, rate populated
  3. Cache miss path → _build_gst_fields called as normal
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

_TOP_MATCH = {
    "hsn_code": "09011110",
    "description": "Coffee, not roasted",
    "score": 0.97,
    "method": "db_match",
}

_CACHED_WITH_GST = {
    "top_match": _TOP_MATCH,
    "confidence": 0.97,
    "gst_rate": 5.0,
    "gst_effective_from": "2017-07-01",
    "gst_effective_to": None,
}

_CACHED_WITHOUT_GST = {
    "top_match": _TOP_MATCH,
    "confidence": 0.97,
    "gst_rate": None,
    "gst_effective_from": None,
    "gst_effective_to": None,
}

_GST_FIELDS_RESULT = {
    "gst_rate": 5.0,
    "gst_note": "GST 5% — effective 01-Jul-2017",
    "gst_effective_from": "2017-07-01",
    "gst_effective_to": None,
}

_GST_DATES_RESULT = {
    "gst_effective_from": "2017-07-01",
    "gst_effective_to": None,
    "gst_note": "GST 5% — effective 01-Jul-2017 (currently active)",
}

_GST_DATES_EMPTY = {
    "gst_effective_from": None,
    "gst_effective_to": None,
    "gst_note": None,
}


# ---------------------------------------------------------------------------
# Helper: build a minimal fake Request + AsyncSession
# ---------------------------------------------------------------------------

def _make_db():
    return MagicMock()


# ---------------------------------------------------------------------------
# Test 1 — cache hit WITH gst_rate: fallback must NOT be called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_cache_hit_with_gst_no_fallback():
    """If the cached entry already has gst_rate set, _build_gst_fields must not be called."""
    from app.models.schemas import PredictRequest

    payload = [PredictRequest(text="coffee beans")]
    fake_db = _make_db()
    fake_request = MagicMock()

    with (
        patch("app.routes.predict.check_rate_limit", new_callable=AsyncMock),
        patch("app.routes.predict.get_cache", new_callable=AsyncMock, return_value=_CACHED_WITH_GST),
        patch("app.routes.predict._build_gst_fields", new_callable=AsyncMock) as mock_build,
        patch("app.routes.predict.get_gst_dates", new_callable=AsyncMock) as mock_dates,
    ):
        from app.routes.predict import predict_bulk
        import io
        response = await predict_bulk(
            body=payload,
            request=fake_request,
            api_key="test-key",
            db=fake_db,
        )
        content = b"".join([chunk async for chunk in response.body_iterator] if hasattr(response, 'body_iterator') else [response.body_iterator])

    mock_build.assert_not_called()
    mock_dates.assert_not_called()

    # CSV should contain the pre-existing GST rate
    csv_text = content.decode()
    assert "5.00" in csv_text


# ---------------------------------------------------------------------------
# Test 2 — cache hit WITHOUT gst_rate: fallback MUST be called and rate populated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_cache_hit_missing_gst_triggers_fallback():
    """If gst_rate is None in the cached entry, _build_gst_fields must be called."""
    from app.models.schemas import PredictRequest

    payload = [PredictRequest(text="coffee beans")]
    fake_db = _make_db()
    fake_request = MagicMock()

    with (
        patch("app.routes.predict.check_rate_limit", new_callable=AsyncMock),
        patch("app.routes.predict.get_cache", new_callable=AsyncMock, return_value=_CACHED_WITHOUT_GST),
        patch(
            "app.routes.predict._build_gst_fields",
            new_callable=AsyncMock,
            return_value=_GST_FIELDS_RESULT,
        ) as mock_build,
        patch(
            "app.routes.predict.get_gst_dates",
            new_callable=AsyncMock,
            return_value=_GST_DATES_RESULT,
        ) as mock_dates,
    ):
        from app.routes.predict import predict_bulk
        response = await predict_bulk(
            body=payload,
            request=fake_request,
            api_key="test-key",
            db=fake_db,
        )
        content = b"".join([chunk async for chunk in response.body_iterator] if hasattr(response, 'body_iterator') else [response.body_iterator])

    mock_build.assert_called_once_with("09011110", fake_db)
    mock_dates.assert_called_once_with("09011110", fake_db)

    csv_text = content.decode()
    assert "5.00" in csv_text
    assert "2017-07-01" in csv_text


# ---------------------------------------------------------------------------
# Test 3 — cache miss: _build_gst_fields called via normal path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_cache_miss_calls_build_gst_fields():
    """On cache miss, _build_gst_fields is called as part of the normal lookup path."""
    from app.models.schemas import PredictRequest

    payload = [PredictRequest(text="coffee beans")]
    fake_db = MagicMock()
    fake_request = MagicMock()

    _match = [{"hsn_code": "09011110", "description": "Coffee, not roasted", "score": 0.91, "method": "db_match"}]

    with (
        patch("app.routes.predict.check_rate_limit", new_callable=AsyncMock),
        patch("app.routes.predict.get_cache", new_callable=AsyncMock, return_value=None),
        patch("app.routes.predict.db.execute", new_callable=AsyncMock, side_effect=Exception("no db")),
        patch("app.routes.predict.match_query", new_callable=AsyncMock, return_value=_match),
        patch("app.routes.predict.score_result", return_value=(0.91, "high")),
        patch(
            "app.routes.predict._build_gst_fields",
            new_callable=AsyncMock,
            return_value=_GST_FIELDS_RESULT,
        ) as mock_build,
        patch(
            "app.routes.predict.get_gst_dates",
            new_callable=AsyncMock,
            return_value=_GST_DATES_EMPTY,
        ),
    ):
        from app.routes.predict import predict_bulk
        response = await predict_bulk(
            body=payload,
            request=fake_request,
            api_key="test-key",
            db=fake_db,
        )
        content = b"".join([chunk async for chunk in response.body_iterator] if hasattr(response, 'body_iterator') else [response.body_iterator])

    mock_build.assert_called_once_with("09011110", fake_db)
    csv_text = content.decode()
    assert "09011110" in csv_text
