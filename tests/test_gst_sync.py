"""
tests/test_gst_sync.py
======================
Integration tests for the GST sync scheduler job and admin API endpoints.

Covers:
  1. sync_gst_rates() writes rows to gst_change_log (in-memory SQLite)
  2. POST /admin/gst/sync returns 200 {status: ok, updated: N}
  3. GET /admin/gst/changes?page=2&per_page=25 returns correct pagination
"""
from __future__ import annotations

import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch
from sqlalchemy import select, func, text


# ---------------------------------------------------------------------------
# Shared mock GST data (3 HSN codes with updated rates)
# ---------------------------------------------------------------------------

_MOCK_RATES = {
    "0101": {"rate": 5.0,  "effective_from": date(2017, 7, 1),  "source": "cbic"},
    "1001": {"rate": 12.0, "effective_from": date(2017, 7, 1),  "source": "cbic"},
    "2201": {"rate": 18.0, "effective_from": date(2024, 1, 1),  "source": "cbic"},
}


# ---------------------------------------------------------------------------
# Test 1 — sync_gst_rates() inserts rows into gst_change_log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_job_writes_change_log(async_db_session):
    """
    Mock fetch_all_gst_rates() + async_session to use our in-memory SQLite.
    Run sync_gst_rates() and assert 3 rows appear in gst_change_log.
    """
    from app.models.database import HsnCode, GstChangeLog
    from sqlalchemy.ext.asyncio import AsyncSession
    from contextlib import asynccontextmanager

    # Seed 3 HsnCode rows in the test DB so the sync can find them
    seed_rows = [
        HsnCode(
            hsn_code=hsn,
            description=f"Test product {hsn}",
            gst_rate_numeric=None,        # NULL → will trigger a change
            gst_effective_from=None,
            gst_updated_at=None,
        )
        for hsn in _MOCK_RATES
    ]
    async_db_session.add_all(seed_rows)
    await async_db_session.commit()

    # Patch async_session to return our test session
    @asynccontextmanager
    async def _fake_session():
        yield async_db_session

    with patch("app.utils.scheduler.fetch_all_gst_rates", new_callable=AsyncMock, return_value=_MOCK_RATES), \
         patch("app.utils.scheduler.async_session", return_value=_fake_session()), \
         patch("app.utils.scheduler.gst_sync_last_run_timestamp") as mock_gauge:

        from app.utils.scheduler import sync_gst_rates
        stats = await sync_gst_rates()

    # All 3 rates were NULL → all 3 should be updated
    assert stats["updated"] == 3, f"Expected 3 updates, got {stats['updated']}"

    # Verify gst_change_log rows
    result = await async_db_session.execute(
        select(func.count()).select_from(GstChangeLog)
    )
    log_count = result.scalar()
    assert log_count == 3, f"Expected 3 rows in gst_change_log, got {log_count}"

    # Gauge was set
    mock_gauge.set.assert_called_once()


# ---------------------------------------------------------------------------
# Test 2 — POST /admin/gst/sync returns 200 {status: ok, updated: N}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_sync_endpoint(admin_client, admin_key):
    """
    POST /admin/gst/sync with a valid admin key.
    trigger_gst_sync_now is mocked to avoid real DB/HTTP calls.
    """
    mock_result = {"updated": 7, "unchanged": 42, "source": "cbic", "duration_ms": 150}

    with patch(
        "app.routes.admin.trigger_gst_sync_now",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = await admin_client.post(
            "/admin/gst/sync",
            headers={"X-API-Key": admin_key},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["status"] == "ok"
    assert body["updated"] == 7
    assert "source" in body


# ---------------------------------------------------------------------------
# Test 3 — GET /admin/gst/changes pagination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_changes_endpoint_pagination(admin_client, admin_key, seeded_change_log):
    """
    Seed 55 rows into gst_change_log.
    Request page=2, per_page=25 and assert correct slice is returned.
    """
    from app.models.database import get_db
    from app.main import app

    # Override the get_db dependency to use our seeded SQLite session
    async def _override_db():
        yield seeded_change_log

    app.dependency_overrides[get_db] = _override_db

    try:
        resp = await admin_client.get(
            "/admin/gst/changes",
            params={"page": 2, "per_page": 25},
            headers={"X-API-Key": admin_key},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    assert body["page"] == 2
    assert len(body["items"]) == 25, (
        f"Expected 25 items on page 2, got {len(body['items'])}"
    )
    assert body["total"] >= 55, (
        f"Expected total >= 55, got {body['total']}"
    )
    assert body["per_page"] == 25
