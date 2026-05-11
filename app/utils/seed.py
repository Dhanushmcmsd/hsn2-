from __future__ import annotations

import structlog
from sqlalchemy import select, update

from app.models.database import ApiKey, Branch, Organisation, Prediction, User, async_session

log = structlog.get_logger()


async def seed_default_org() -> None:
    async with async_session() as session:
        org = (
            await session.execute(
                select(Organisation).order_by(Organisation.created_at.asc())
            )
        ).scalars().first()
        if org is None:
            org = Organisation(name="HQ", gstin_prefix=None, is_active=True)
            session.add(org)
            await session.flush()

        branch = (
            await session.execute(
                select(Branch).order_by(Branch.created_at.asc())
            )
        ).scalars().first()
        if branch is None:
            branch = Branch(
                organisation_id=org.id,
                name="Default Branch",
                is_active=True,
            )
            session.add(branch)
            await session.flush()

        await session.execute(
            update(User).where(User.branch_id.is_(None)).values(branch_id=branch.id)
        )
        await session.execute(
            update(Prediction).where(Prediction.branch_id.is_(None)).values(branch_id=branch.id)
        )
        await session.execute(
            update(ApiKey).where(ApiKey.branch_id.is_(None)).values(branch_id=branch.id)
        )
        await session.commit()
        log.info("seed.default_org_branch_done", organisation_id=str(org.id), branch_id=str(branch.id))
