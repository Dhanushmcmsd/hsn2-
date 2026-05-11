from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select

from app.models.database import async_session
from app.models.gst_rate_history import GSTRateHistory


async def seed() -> None:
    df = pd.read_csv("data/hsn_codes_full.csv")
    created = 0
    updated = 0
    unchanged = 0
    async with async_session() as session:
        for _, row in df.iterrows():
            hsn = str(row.get("hsn_code", "")).strip()
            if not hsn:
                continue
            rate = float(row.get("gst_rate", 0))
            active = (
                await session.execute(
                    select(GSTRateHistory).where(
                        GSTRateHistory.hsn_code == hsn,
                        GSTRateHistory.effective_to.is_(None),
                    )
                )
            ).scalars().first()
            if active is None:
                session.add(
                    GSTRateHistory(
                        hsn_code=hsn,
                        gst_rate=rate,
                        effective_from=date(2022, 1, 1),
                        effective_to=None,
                        source_url="data/hsn_codes_full.csv",
                    )
                )
                created += 1
            elif float(active.gst_rate) != rate:
                active.effective_to = date.today() - timedelta(days=1)
                session.add(
                    GSTRateHistory(
                        hsn_code=hsn,
                        gst_rate=rate,
                        effective_from=date.today(),
                        effective_to=None,
                        source_url="data/hsn_codes_full.csv",
                    )
                )
                updated += 1
            else:
                unchanged += 1
        await session.commit()
    print(f"Seeded {created} new, {updated} updated, {unchanged} unchanged.")


if __name__ == "__main__":
    asyncio.run(seed())
