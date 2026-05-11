from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from app.models.gst_rate_history import GSTRateHistory


@pytest.mark.asyncio
async def test_single_active_row_after_migration_repair(async_db_session):
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

    await async_db_session.execute(
        text(
            """
            UPDATE gst_rate_history
            SET effective_to = date(
                (
                    SELECT MIN(n.effective_from)
                    FROM gst_rate_history n
                    WHERE n.hsn_code = gst_rate_history.hsn_code
                      AND n.effective_to IS NULL
                      AND n.effective_from > gst_rate_history.effective_from
                ),
                '-1 day'
            )
            WHERE effective_to IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM gst_rate_history x
                  WHERE x.hsn_code = gst_rate_history.hsn_code
                    AND x.effective_to IS NULL
                    AND x.effective_from > gst_rate_history.effective_from
              );
            """
        )
    )
    await async_db_session.commit()

    active_rows = (
        await async_db_session.execute(
            text(
                """
                SELECT effective_from
                FROM gst_rate_history
                WHERE hsn_code = :hsn_code
                  AND effective_to IS NULL
                """
            ),
            {"hsn_code": hsn_code},
        )
    ).all()

    assert len(active_rows) == 1
    assert active_rows[0][0] == "2025-01-01"
