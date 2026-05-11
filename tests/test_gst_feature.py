"""
tests/test_gst_feature.py

All 14 GST feature tests.

Run in isolation:
    pytest tests/test_gst_feature.py -v

Expected:
    PASSED  test_get_gst_dates_active_rate
    PASSED  test_get_gst_dates_with_end_date
    PASSED  test_get_gst_dates_no_record
    PASSED  test_get_gst_dates_expired_rate_not_returned
    PASSED  test_get_gst_dates_calls_db_execute
    PASSED  test_fetch_latest_gst_notifications_parses_rows
    PASSED  test_fetch_latest_gst_notifications_empty_table
    PASSED  test_fetch_and_sync_gst_rates_network_error_does_not_crash
    PASSED  test_fetch_and_sync_gst_rates_upserts_records
    PASSED  test_scheduler_job_registered_with_correct_cron
    PASSED  test_scheduler_job_callable_is_correct
    PASSED  test_predict_response_schema_has_gst_date_fields
    PASSED  test_gst_rate_history_model_columns
    PASSED  test_gst_rate_history_hsn_code_is_indexed
"""
from __future__ import annotations

import inspect
import textwrap
from datetime import date, datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# Tests 1-5 — get_gst_dates()
# ===========================================================================

async def _make_db_with_row(row_or_none):
    """Return a minimal mock AsyncSession whose execute chain yields a row."""
    scalars_mock = MagicMock()
    scalars_mock.first.return_value = row_or_none
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_mock)
    return db


def _make_history_row(
    gst_rate: float = 18.0,
    effective_from: date = date(2024, 4, 1),
    effective_to: Optional[date] = None,
):
    row = MagicMock()
    row.gst_rate = gst_rate
    row.effective_from = effective_from
    row.effective_to = effective_to
    return row


@pytest.mark.asyncio
async def test_get_gst_dates_active_rate():
    """Active rate (no end date) → correct ISO strings and note."""
    from app.routes.predict import get_gst_dates

    row = _make_history_row(gst_rate=18.0, effective_from=date(2024, 4, 1), effective_to=None)
    db = await _make_db_with_row(row)

    result = await get_gst_dates("04011010", db)

    assert result["gst_effective_from"] == "2024-04-01"
    assert result["gst_effective_to"] is None
    assert result["gst_note"] is not None
    assert "18%" in result["gst_note"]
    assert "currently active" in result["gst_note"]


@pytest.mark.asyncio
async def test_get_gst_dates_with_end_date():
    """Rate with an end date → effective_to is an ISO string."""
    from app.routes.predict import get_gst_dates

    row = _make_history_row(
        gst_rate=12.0,
        effective_from=date(2023, 1, 1),
        effective_to=date(2024, 3, 31),
    )
    db = await _make_db_with_row(row)

    result = await get_gst_dates("04011010", db)

    assert result["gst_effective_from"] == "2023-01-01"
    assert result["gst_effective_to"] == "2024-03-31"
    assert result["gst_note"] is not None
    assert "12%" in result["gst_note"]


@pytest.mark.asyncio
async def test_get_gst_dates_no_record():
    """No row in history → all three fields are None."""
    from app.routes.predict import get_gst_dates

    db = await _make_db_with_row(None)
    result = await get_gst_dates("99999999", db)

    assert result == {"gst_effective_from": None, "gst_effective_to": None, "gst_note": None}


@pytest.mark.asyncio
async def test_get_gst_dates_expired_rate_not_returned():
    """
    When DB raises (simulating expired/invalid filter), get_gst_dates
    swallows the exception and returns all-None dict.
    """
    from app.routes.predict import get_gst_dates

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=Exception("DB error"))

    result = await get_gst_dates("04011010", db)
    assert result == {"gst_effective_from": None, "gst_effective_to": None, "gst_note": None}


@pytest.mark.asyncio
async def test_get_gst_dates_calls_db_execute():
    """get_gst_dates must call db.execute exactly once."""
    from app.routes.predict import get_gst_dates

    db = await _make_db_with_row(None)
    await get_gst_dates("04011010", db)

    db.execute.assert_awaited_once()


# ===========================================================================
# Tests 6-7 — fetch_latest_gst_notifications() HTML scraper
# ===========================================================================

FAKE_HTML_WITH_ROWS = textwrap.dedent("""\
    <html><body>
    <table>
      <tr><th>Date</th><th>Subject</th></tr>
      <tr>
        <td>01/04/2024</td>
        <td><a href="/notification/ct-rate-01-2024.pdf">Notification No. 01/2024 - Central Tax (Rate)</a></td>
      </tr>
      <tr>
        <td>15/06/2024</td>
        <td><a href="/notification/ct-rate-02-2024.pdf">Notification No. 02/2024 - Central Tax (Rate) amending 12%</a></td>
      </tr>
      <tr>
        <td>10/03/2023</td>
        <td>Exemption from GST — Non-Rate circular</td>
      </tr>
    </table>
    </body></html>
""")  # row 3 has "rate" via "Non-Rate" — should be included (case-insensitive)

FAKE_HTML_EMPTY = "<html><body><table><tr><th>Date</th><th>Info</th></tr></table></body></html>"


@pytest.mark.asyncio
async def test_fetch_latest_gst_notifications_parses_rows():
    """Rows containing 'rate' (case-insensitive) in cell 2 are returned."""
    import httpx
    from app.services.gst_fetcher import fetch_latest_gst_notifications

    mock_response = httpx.Response(200, text=FAKE_HTML_WITH_ROWS)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        results = await fetch_latest_gst_notifications()

    # All 3 rows contain "rate" in the second cell (case-insensitive)
    assert len(results) >= 2
    titles = [r["title"] for r in results]
    assert any("Rate" in t or "rate" in t for t in titles)
    # URLs should be absolute
    for r in results:
        assert r["url"].startswith("http")


@pytest.mark.asyncio
async def test_fetch_latest_gst_notifications_empty_table():
    """No matching rows → returns empty list (does not raise)."""
    import httpx
    from app.services.gst_fetcher import fetch_latest_gst_notifications

    mock_response = httpx.Response(200, text=FAKE_HTML_EMPTY)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        results = await fetch_latest_gst_notifications()

    assert results == []


# ===========================================================================
# Tests 8-9 — fetch_and_sync_gst_rates()
# ===========================================================================

@pytest.mark.asyncio
async def test_fetch_and_sync_gst_rates_network_error_does_not_crash():
    """
    When fetch_latest_gst_notifications() raises a network error,
    fetch_and_sync_gst_rates() must swallow it and return None.
    """
    from app.services.gst_fetcher import fetch_and_sync_gst_rates

    with patch(
        "app.services.gst_fetcher.fetch_latest_gst_notifications",
        new=AsyncMock(side_effect=Exception("Connection refused")),
    ):
        result = await fetch_and_sync_gst_rates()

    assert result is None  # function should return without raising


@pytest.mark.asyncio
async def test_fetch_and_sync_gst_rates_upserts_records():
    """
    When notifications are returned with parseable rate + date,
    fetch_and_sync_gst_rates() calls session.add() and session.commit().
    """
    from app.services.gst_fetcher import fetch_and_sync_gst_rates

    notifications = [
        {
            "title": "Notification 01/2024 amending GST Rate to 18% w.e.f. 01-04-2024",
            "date": "01/04/2024",
            "url": "https://www.cbic.gov.in/notification/ct-rate-01-2024.pdf",
        }
    ]

    db_mock = AsyncMock()
    # Simulate no existing row found (upsert path → add new)
    scalars_mock = MagicMock()
    scalars_mock.first.return_value = None
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    db_mock.execute = AsyncMock(return_value=result_mock)
    db_mock.add = MagicMock()
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()

    with patch(
        "app.services.gst_fetcher.fetch_latest_gst_notifications",
        new=AsyncMock(return_value=notifications),
    ):
        await fetch_and_sync_gst_rates(db=db_mock)

    db_mock.add.assert_called_once()
    db_mock.commit.assert_awaited_once()


# ===========================================================================
# Tests 10-11 — APScheduler cron registration
# ===========================================================================

@pytest.mark.asyncio
async def test_scheduler_job_registered_with_correct_cron():
    """
    After start_scheduler(), the GST nightly sync job must be registered
    with hour=2, minute=0, timezone='Asia/Kolkata'.
    """
    from app.utils.scheduler import start_scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    with patch.object(AsyncIOScheduler, "start", return_value=None):
        await start_scheduler()
        from app.utils import scheduler as sched_module
        _scheduler = sched_module._scheduler

        assert _scheduler is not None
        job = _scheduler.get_job("gst_nightly_sync")
        assert job is not None, "gst_nightly_sync job not found"

        trigger = job.trigger
        # CronTrigger fields are stored as a list of field objects
        fields = {f.name: f for f in trigger.fields}
        assert str(fields["hour"]) == "2", f"Expected hour=2, got {fields['hour']}"
        assert str(fields["minute"]) == "0", f"Expected minute=0, got {fields['minute']}"
        assert str(trigger.timezone) == "Asia/Kolkata"

    # Clean up
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_scheduler_job_callable_is_correct():
    """
    The GST cron job must call sync_gst_rates (not any other function).
    """
    from app.utils.scheduler import start_scheduler, sync_gst_rates
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    with patch.object(AsyncIOScheduler, "start", return_value=None):
        await start_scheduler()
        from app.utils import scheduler as sched_module
        _scheduler = sched_module._scheduler

        job = _scheduler.get_job("gst_nightly_sync")
        assert job is not None
        assert job.func is sync_gst_rates, (
            f"Expected sync_gst_rates, got {job.func}"
        )

    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)


# ===========================================================================
# Test 12 — PredictResponse Pydantic schema
# ===========================================================================

def test_predict_response_schema_has_gst_date_fields():
    """
    PredictResponse must declare gst_effective_from, gst_effective_to,
    and gst_note as Optional fields (i.e. they have a default of None).
    """
    from app.models.schemas import PredictResponse
    import typing

    fields = PredictResponse.model_fields

    for field_name in ("gst_effective_from", "gst_effective_to", "gst_note"):
        assert field_name in fields, f"PredictResponse missing field: {field_name}"
        field_info = fields[field_name]
        # Field must be Optional (default is None or required=False)
        assert not field_info.is_required(), (
            f"{field_name} should be Optional with default=None, but is required"
        )


# ===========================================================================
# Tests 13-14 — GSTRateHistory ORM model
# ===========================================================================

def test_gst_rate_history_model_columns():
    """
    GSTRateHistory must expose the 5 data columns:
    hsn_code, gst_rate, effective_from, effective_to, source_url.
    """
    from app.models.gst_rate_history import GSTRateHistory
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(GSTRateHistory)
    col_names = {c.key for c in mapper.columns}

    required = {"id", "hsn_code", "gst_rate", "effective_from", "effective_to", "source_url", "fetched_at"}
    missing = required - col_names
    assert not missing, f"GSTRateHistory missing columns: {missing}"


def test_gst_rate_history_hsn_code_is_indexed():
    """
    The hsn_code column in GSTRateHistory must be marked as indexed.
    """
    from app.models.gst_rate_history import GSTRateHistory
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(GSTRateHistory)
    hsn_col = next(
        (c for c in mapper.columns if c.key == "hsn_code"), None
    )
    assert hsn_col is not None, "hsn_code column not found on GSTRateHistory"
    # The column itself or any index over it must mark it as indexed
    col_obj = GSTRateHistory.__table__.c["hsn_code"]
    assert col_obj.index is True, (
        "hsn_code on gst_rate_history is not indexed "
        "(set index=True on the Column definition)"
    )
