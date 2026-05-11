"""Admin API for Organisation and Branch management.

All endpoints require the ADMIN_API_KEY header.
"""
from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import get_db, Organisation, Branch
from app.models.schemas import (
    BranchCreate, BranchRead,
    OrganisationCreate, OrganisationRead,
)

router = APIRouter(prefix="/admin", tags=["admin-orgs"])


def _require_admin(x_admin_api_key: str = Header(..., alias="X-Admin-API-Key")) -> None:
    if x_admin_api_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin key")


# ---------------------------------------------------------------------------
# Organisation endpoints
# ---------------------------------------------------------------------------

@router.post("/orgs", response_model=OrganisationRead, status_code=status.HTTP_201_CREATED)
async def create_org(
    payload: OrganisationCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """Create a new organisation."""
    existing = (await db.execute(
        select(Organisation).where(Organisation.name == payload.name)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Organisation name already exists")

    org = Organisation(**payload.model_dump())
    db.add(org)
    await db.commit()
    await db.refresh(org)

    branch_count = (await db.execute(
        select(func.count()).select_from(Branch).where(Branch.organisation_id == org.id)
    )).scalar()
    return OrganisationRead(
        id=org.id, name=org.name, gstin_prefix=org.gstin_prefix,
        is_active=org.is_active, created_at=org.created_at,
        branch_count=branch_count,
    )


@router.get("/orgs", response_model=List[OrganisationRead])
async def list_orgs(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """List all organisations with their branch count."""
    orgs = (await db.execute(select(Organisation))).scalars().all()
    result = []
    for org in orgs:
        branch_count = (await db.execute(
            select(func.count()).select_from(Branch).where(Branch.organisation_id == org.id)
        )).scalar()
        result.append(OrganisationRead(
            id=org.id, name=org.name, gstin_prefix=org.gstin_prefix,
            is_active=org.is_active, created_at=org.created_at,
            branch_count=branch_count,
        ))
    return result


# ---------------------------------------------------------------------------
# Branch endpoints
# ---------------------------------------------------------------------------

@router.post("/orgs/{org_id}/branches", response_model=BranchRead, status_code=status.HTTP_201_CREATED)
async def create_branch(
    org_id: UUID,
    payload: BranchCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """Create a branch under an organisation."""
    org = (await db.execute(select(Organisation).where(Organisation.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    branch = Branch(organisation_id=org_id, **payload.model_dump())
    db.add(branch)
    try:
        await db.commit()
        await db.refresh(branch)
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Branch name already exists in this organisation")
    return branch


@router.get("/orgs/{org_id}/branches", response_model=List[BranchRead])
async def list_branches(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """List all branches for an organisation."""
    org = (await db.execute(select(Organisation).where(Organisation.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    branches = (await db.execute(
        select(Branch).where(Branch.organisation_id == org_id)
    )).scalars().all()
    return branches


@router.patch("/branches/{branch_id}", response_model=BranchRead)
async def update_branch(
    branch_id: UUID,
    payload: BranchCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """Update branch fields."""
    branch = (await db.execute(select(Branch).where(Branch.id == branch_id))).scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(branch, field, value)
    await db.commit()
    await db.refresh(branch)
    return branch


@router.delete("/branches/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_branch(
    branch_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """Soft-delete a branch (sets is_active=False)."""
    branch = (await db.execute(select(Branch).where(Branch.id == branch_id))).scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    await db.execute(
        update(Branch).where(Branch.id == branch_id).values(is_active=False)
    )
    await db.commit()
