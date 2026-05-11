import asyncio
from datetime import date

from sqlalchemy import select

from app.models.database import async_session
from app.models.gst_rate_history import GSTRateHistory
from app.services.dataset import load_hsn_dataset


async def seed():
    dataset = load_hsn_dataset()
    async with async_session() as session:
        inserted = updated = unchanged = 0
        for entry in dataset:
            try:
                rate = float(entry.gst_rate)
            except Exception:
                continue
            result = await session.execute(
                select(GSTRateHistory)
                .where(GSTRateHistory.hsn_code == entry.hsn_code)
                .where(GSTRateHistory.effective_to.is_(None))
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                session.add(
                    GSTRateHistory(
                        hsn_code=entry.hsn_code,
                        gst_rate=rate,
                        effective_from=date(2022, 1, 1),
                        effective_to=None,
                        source_url="data/hsn_codes_full.csv",
                    )
                )
                inserted += 1
            elif float(existing.gst_rate) != rate:
                existing.effective_to = date.today()
                session.add(
                    GSTRateHistory(
                        hsn_code=entry.hsn_code,
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
        print(f"Seeded {inserted} new, {updated} updated, {unchanged} unchanged.")


if __name__ == "__main__":
    asyncio.run(seed())
