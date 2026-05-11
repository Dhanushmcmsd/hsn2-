from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models.gst_rate_history import GSTRateHistory
from app.services.gst_fetcher import fetch_and_sync_gst_rates


@pytest.mark.asyncio
async def test_gst_history_single_active_row_after_sync(async_db_session):
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
            "title": f"Rate revision for HSN {hsn_code} to 28%",
            "date": "01/01/2026",
            "url": "https://example.com/n4",
        }
    ]

    from unittest.mock import AsyncMock, patch

    with patch(
        "app.services.gst_fetcher.fetch_latest_gst_notifications",
        new_callable=AsyncMock,
        return_value=notifications,
    ):
        await fetch_and_sync_gst_rates(async_db_session)

    rows = (
        await async_db_session.execute(
            select(GSTRateHistory).where(
                GSTRateHistory.hsn_code == hsn_code,
                GSTRateHistory.effective_to.is_(None),
            )
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].effective_from == date(2026, 1, 1)
