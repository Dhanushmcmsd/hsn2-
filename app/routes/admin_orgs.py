from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Branch, Organisation, get_db
from app.models.schemas import BranchCreate, BranchRead, BranchUpdate, OrganisationCreate, OrganisationRead
from app.utils.auth import require_admin_key

router = APIRouter(prefix="/admin", tags=["admin-orgs"])


@router.post("/orgs", response_model=OrganisationRead)
async def create_org(
    body: OrganisationCreate,
    admin_key: str = Depends(require_admin_key),
    db: AsyncSession = Depends(get_db),
):
    _ = admin_key
    exists = (
        await db.execute(select(Organisation).where(Organisation.name == body.name))
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=409, detail="Organisation already exists")
    org = Organisation(name=body.name, gstin_prefix=body.gstin_prefix, is_active=True)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return OrganisationRead(
        id=org.id,
        name=org.name,
        gstin_prefix=org.gstin_prefix,
        is_active=org.is_active,
        created_at=org.created_at,
        branch_count=0,
    )


@router.get("/orgs", response_model=list[OrganisationRead])
async def list_orgs(
    admin_key: str = Depends(require_admin_key),
    db: AsyncSession = Depends(get_db),
):
    _ = admin_key
    rows = await db.execute(
        select(
            Organisation,
            func.count(Branch.id).label("branch_count"),
        )
        .outerjoin(Branch, Branch.organisation_id == Organisation.id)
        .group_by(Organisation.id)
        .order_by(Organisation.created_at.asc())
    )
    return [
        OrganisationRead(
            id=org.id,
            name=org.name,
            gstin_prefix=org.gstin_prefix,
            is_active=org.is_active,
            created_at=org.created_at,
            branch_count=int(branch_count or 0),
        )
        for org, branch_count in rows.all()
    ]


@router.post("/orgs/{org_id}/branches", response_model=BranchRead)
async def create_branch(
    org_id: UUID,
    body: BranchCreate,
    admin_key: str = Depends(require_admin_key),
    db: AsyncSession = Depends(get_db),
):
    _ = admin_key
    org = (
        await db.execute(select(Organisation).where(Organisation.id == org_id))
    ).scalars().first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")
    branch = Branch(
        organisation_id=org.id,
        name=body.name,
        city=body.city,
        state_code=body.state_code,
        gstin=body.gstin,
        is_active=True,
    )
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return branch


@router.get("/orgs/{org_id}/branches", response_model=list[BranchRead])
async def list_branches(
    org_id: UUID,
    admin_key: str = Depends(require_admin_key),
    db: AsyncSession = Depends(get_db),
):
    _ = admin_key
    rows = await db.execute(
        select(Branch).where(Branch.organisation_id == org_id).order_by(Branch.created_at.asc())
    )
    return rows.scalars().all()


@router.patch("/branches/{branch_id}", response_model=BranchRead)
async def update_branch(
    branch_id: UUID,
    body: BranchUpdate,
    admin_key: str = Depends(require_admin_key),
    db: AsyncSession = Depends(get_db),
):
    _ = admin_key
    branch = (
        await db.execute(select(Branch).where(Branch.id == branch_id))
    ).scalars().first()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    if body.name is not None:
        branch.name = body.name
    if body.city is not None:
        branch.city = body.city
    if body.state_code is not None:
        branch.state_code = body.state_code
    if body.gstin is not None:
        branch.gstin = body.gstin
    await db.commit()
    await db.refresh(branch)
    return branch


@router.delete("/branches/{branch_id}")
async def soft_delete_branch(
    branch_id: UUID,
    admin_key: str = Depends(require_admin_key),
    db: AsyncSession = Depends(get_db),
):
    _ = admin_key
    branch = (
        await db.execute(select(Branch).where(Branch.id == branch_id))
    ).scalars().first()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    branch.is_active = False
    await db.commit()
    return {"status": "ok", "branch_id": str(branch.id), "is_active": branch.is_active}
