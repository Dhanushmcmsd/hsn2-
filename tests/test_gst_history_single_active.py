from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.gst_rate_history import GSTRateHistory
from app.services.gst_fetcher import fetch_and_sync_gst_rates


@pytest.mark.asyncio
async def test_single_active_row_after_sync(async_db_session):
    hsn_code = "04011010"

    async_db_session.add_all(
        [
            GSTRateHistory(
                hsn_code=hsn_code,
                gst_rate=5.0,
                effective_from=date(2023, 1, 1),
                effective_to=None,
                source_url="https://example.com/n1",
            ),
            GSTRateHistory(
                hsn_code=hsn_code,
                gst_rate=12.0,
                effective_from=date(2024, 1, 1),
                effective_to=None,
                source_url="https://example.com/n2",
            ),
            GSTRateHistory(
                hsn_code=hsn_code,
                gst_rate=18.0,
                effective_from=date(2025, 1, 1),
                effective_to=None,
                source_url="https://example.com/n3",
            ),
        ]
    )
    await async_db_session.commit()

    notifications = [
        {
            "title": f"Rate revision for HSN {hsn_code} to 18%",
            "date": "01/01/2025",
            "url": "https://example.com/n3",  # existing source+effective_from
        }
    ]

    with patch(
        "app.services.gst_fetcher.fetch_latest_gst_notifications",
        new_callable=AsyncMock,
        return_value=notifications,
    ):
        await fetch_and_sync_gst_rates(async_db_session)

    active_rows = (
        await async_db_session.execute(
            select(GSTRateHistory).where(
                GSTRateHistory.hsn_code == hsn_code,
                GSTRateHistory.effective_to.is_(None),
            )
        )
    ).scalars().all()

    assert len(active_rows) == 1
    assert active_rows[0].effective_from == date(2025, 1, 1)


@pytest.mark.asyncio
async def test_new_insert_closes_prior(async_db_session):
    hsn_code = "04011010"

    async_db_session.add(
        GSTRateHistory(
            hsn_code=hsn_code,
            gst_rate=12.0,
            effective_from=date(2024, 1, 1),
            effective_to=None,
            source_url="https://example.com/old",
        )
    )
    await async_db_session.commit()

    notifications = [
        {
            "title": f"Rate revision for HSN {hsn_code} to 18%",
            "date": "01/06/2025",
            "url": "https://example.com/new",
        }
    ]

    with patch(
        "app.services.gst_fetcher.fetch_latest_gst_notifications",
        new_callable=AsyncMock,
        return_value=notifications,
    ):
        await fetch_and_sync_gst_rates(async_db_session)

    rows = (
        await async_db_session.execute(
            select(GSTRateHistory).where(GSTRateHistory.hsn_code == hsn_code)
        )
    ).scalars().all()

    assert len(rows) == 2

    old_row = next(r for r in rows if r.source_url == "https://example.com/old")
    new_row = next(r for r in rows if r.source_url == "https://example.com/new")

    assert old_row.effective_to == date(2025, 5, 31)
    assert new_row.effective_to is None
    assert new_row.effective_from == date(2025, 6, 1)
