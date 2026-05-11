from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import User, UserRole, get_db
from app.models.schemas import UserRoleUpdate
from app.routes.auth import require_role
from app.services.audit import EventType, log_event

router = APIRouter(prefix="/admin", tags=["admin-users"])


@router.get("/users")
async def list_users(
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    rows = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    return [
        {
            "id": row.id,
            "email": row.email,
            "role": row.role.value if isinstance(row.role, UserRole) else row.role,
            "branch_id": str(row.branch_id) if row.branch_id else None,
            "last_login": None,
            "is_active": row.is_active,
        }
        for row in rows
    ]


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    body: UserRoleUpdate,
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    old_role = target.role.value if isinstance(target.role, UserRole) else target.role
    target.role = body.role
    target.branch_id = body.branch_id
    await log_event(
        session=db,
        event_type=EventType.USER_ROLE_CHANGED,
        actor_user_id=current_user.id,
        actor_role=current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role),
        branch_id=current_user.branch_id,
        entity_type="user",
        entity_id=str(target.id),
        old_value={"role": old_role},
        new_value={"role": body.role},
    )
    await db.commit()
    return {"status": "ok", "user_id": target.id, "old_role": old_role, "new_role": body.role}


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = False
    await db.commit()
    return {"status": "ok", "user_id": target.id, "is_active": target.is_active}
