from __future__ import annotations

import hashlib
import uuid
import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_hq_admin_can_update_api_key_tier(client):
    from app.models.database import ApiKey, User, UserRole, async_session

    email = "tier_admin@example.com"
    password = "pass123456"

    await client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Tier Admin"},
    )

    async with async_session() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalars().first()
        user.role = UserRole.HQ_ADMIN.value
        key_hash = hashlib.sha256(f"{email}-tier-key-{uuid.uuid4()}".encode()).hexdigest()
        key = ApiKey(key_hash=key_hash, label="test-key", tier="standard", is_active=True)
        db.add(key)
        await db.commit()
        await db.refresh(key)
        key_id = key.id

    login = await client.post("/auth/login", data={"username": email, "password": password})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    resp = await client.patch(
        f"/admin/api-keys/{key_id}/tier",
        json={"tier": "enterprise"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["new_tier"] == "enterprise"
