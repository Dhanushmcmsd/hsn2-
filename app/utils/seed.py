"""Startup seed: ensure HQ organisation + Default Branch exist.

Call seed_default_org() from the FastAPI lifespan after init_db().
All existing Users, Predictions, and ApiKeys without a branch_id are
assigned to the Default Branch so zero data is lost on upgrade.
"""
from __future__ import annotations

import structlog
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import async_session, Organisation, Branch, User, Prediction, ApiKey

log = structlog.get_logger()


async def seed_default_org() -> None:
    """Idempotent: create HQ org + Default Branch and backfill existing rows."""
    async with async_session() as session:
        # 1. Create HQ organisation if none exists
        org_count = (await session.execute(
            select(func.count()).select_from(Organisation)
        )).scalar()

        if org_count == 0:
            hq = Organisation(name="HQ", is_active=True)
            session.add(hq)
            await session.flush()  # populate hq.id
        else:
            hq = (await session.execute(
                select(Organisation).where(Organisation.name == "HQ")
            )).scalar_one_or_none()
            if hq is None:
                # HQ was renamed; just grab the first active org
                hq = (await session.execute(
                    select(Organisation).where(Organisation.is_active == True).limit(1)
                )).scalar_one()

        # 2. Create Default Branch if none exists
        branch_count = (await session.execute(
            select(func.count()).select_from(Branch)
        )).scalar()

        if branch_count == 0:
            default_branch = Branch(
                organisation_id=hq.id,
                name="Default Branch",
                is_active=True,
            )
            session.add(default_branch)
            await session.flush()  # populate default_branch.id
        else:
            default_branch = (await session.execute(
                select(Branch).where(
                    Branch.organisation_id == hq.id,
                    Branch.name == "Default Branch",
                )
            )).scalar_one_or_none()
            if default_branch is None:
                # grab first branch under this org
                default_branch = (await session.execute(
                    select(Branch).where(Branch.organisation_id == hq.id).limit(1)
                )).scalar_one()

        branch_id = default_branch.id

        # 3. Backfill existing rows that have no branch_id
        await session.execute(
            update(User).where(User.branch_id == None).values(branch_id=branch_id)  # noqa: E711
        )
        await session.execute(
            update(Prediction).where(Prediction.branch_id == None).values(branch_id=branch_id)  # noqa: E711
        )
        await session.execute(
            update(ApiKey).where(ApiKey.branch_id == None).values(branch_id=branch_id)  # noqa: E711
        )

        await session.commit()
        log.info("Seeded default org and branch", org_id=str(hq.id), branch_id=str(branch_id))
