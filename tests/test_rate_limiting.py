from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.utils.rate_limit import check_rate_limit


class FakeRedis:
    def __init__(self):
        self.d = {}

    async def get(self, k):
        return self.d.get(k)

    async def setex(self, k, ttl, v):
        self.d[k] = v

    async def incr(self, k):
        self.d[k] = int(self.d.get(k, 0)) + 1
        return self.d[k]

    async def expire(self, k, ttl):
        return True

    async def delete(self, k):
        self.d.pop(k, None)


@pytest.mark.asyncio
async def test_free_tier_blocked_at_101(monkeypatch):
    r = FakeRedis()
    async def _gr():
        return r
    monkeypatch.setattr("app.utils.rate_limit.get_redis", _gr)
    monkeypatch.setattr("app.utils.rate_limit._resolve_tier", lambda api_key: __import__('asyncio').sleep(0, result='free'))
    for _ in range(100):
        await check_rate_limit("free_key_12345678", endpoint="predict")
    with pytest.raises(HTTPException) as ex:
        await check_rate_limit("free_key_12345678", endpoint="predict")
    assert ex.value.status_code == 429


@pytest.mark.asyncio
async def test_enterprise_allows_high_volume(monkeypatch):
    r = FakeRedis()
    async def _gr():
        return r
    monkeypatch.setattr("app.utils.rate_limit.get_redis", _gr)
    monkeypatch.setattr("app.utils.rate_limit._resolve_tier", lambda api_key: __import__('asyncio').sleep(0, result='enterprise'))
    for _ in range(1000):
        await check_rate_limit("ent_key_12345678", endpoint="predict")


@pytest.mark.asyncio
async def test_rate_limit_headers_present(monkeypatch):
    r = FakeRedis()
    async def _gr():
        return r
    monkeypatch.setattr("app.utils.rate_limit.get_redis", _gr)
    monkeypatch.setattr("app.utils.rate_limit._resolve_tier", lambda api_key: __import__('asyncio').sleep(0, result='standard'))
    headers = await check_rate_limit("std_key_12345678", endpoint="predict")
    assert "X-RateLimit-Limit" in headers
    assert "X-RateLimit-Remaining" in headers
    assert "X-RateLimit-Reset" in headers


@pytest.mark.asyncio
async def test_admin_can_update_tier(client):
    from app.models.database import ApiKey, User, UserRole, async_session
    from sqlalchemy import select

    email = f"hq_{uuid.uuid4().hex[:8]}@example.com"
    password = "pass123456"
    await client.post("/auth/register", json={"email": email, "password": password, "full_name": "HQ"})
    async with async_session() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalars().first()
        u.role = UserRole.HQ_ADMIN.value
        k = ApiKey(key_hash="abc123", tier="standard", role=UserRole.BRANCH_USER.value, is_active=True)
        db.add(k)
        await db.commit()
        key_id = k.id
    login = await client.post("/auth/login", data={"username": email, "password": password}, headers={"Content-Type": "application/x-www-form-urlencoded"})
    token = login.json()["access_token"]
    resp = await client.patch(f"/admin/api-keys/{key_id}/tier", json={"tier": "enterprise"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_branch_user_cannot_update_tier(client):
    from app.models.database import ApiKey, User, UserRole, async_session
    from sqlalchemy import select

    email = f"bu_{uuid.uuid4().hex[:8]}@example.com"
    password = "pass123456"
    await client.post("/auth/register", json={"email": email, "password": password, "full_name": "BU"})
    async with async_session() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalars().first()
        u.role = UserRole.BRANCH_USER.value
        k = ApiKey(key_hash="def123", tier="standard", role=UserRole.BRANCH_USER.value, is_active=True)
        db.add(k)
        await db.commit()
        key_id = k.id
    login = await client.post("/auth/login", data={"username": email, "password": password}, headers={"Content-Type": "application/x-www-form-urlencoded"})
    token = login.json()["access_token"]
    resp = await client.patch(f"/admin/api-keys/{key_id}/tier", json={"tier": "enterprise"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
