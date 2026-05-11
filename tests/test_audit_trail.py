from __future__ import annotations

import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select


@pytest.mark.asyncio
async def test_prediction_creates_audit_event(client):
    from app.main import app
    from app.models.database import AuditLog, Prediction, User, UserRole, get_db

    email = f"audit_{uuid.uuid4().hex[:8]}@example.com"
    password = "pass123456"

    # Register + elevate to BRANCH_USER (predict route requires authenticated role)
    await client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Audit User"},
    )

    from app.models.database import async_session
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalars().first()
        user.role = UserRole.BRANCH_USER.value
        await db.commit()

    login = await client.post(
        "/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    resp = await client.post(
        "/predict",
        json={"text": "basmati rice 5kg"},
        headers={"Authorization": f"Bearer {token}", "X-API-Key": "dev-api-key"},
    )
    assert resp.status_code == 200, resp.text

    # Promote same user to HQ_ADMIN for audit-log read
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalars().first()
        user.role = UserRole.HQ_ADMIN.value
        await db.commit()

    login_admin = await client.post(
        "/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    admin_token = login_admin.json()["access_token"]

    audit_resp = await client.get(
        "/admin/audit-log?event_type=prediction.created",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit_resp.status_code == 200, audit_resp.text
    rows = audit_resp.json()
    assert any(r["event_type"] == "prediction.created" for r in rows)


@pytest.mark.asyncio
async def test_audit_export_returns_csv(client):
    from app.models.database import User, UserRole, async_session

    email = f"audit_export_{uuid.uuid4().hex[:8]}@example.com"
    password = "pass123456"
    await client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Audit Export"},
    )

    async with async_session() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalars().first()
        user.role = UserRole.HQ_ADMIN.value
        await db.commit()

    login = await client.post(
        "/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login.json()["access_token"]

    resp = await client.get(
        "/admin/audit-log/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-type", "").startswith("text/csv")


@pytest.mark.asyncio
async def test_non_privileged_user_gets_403_on_audit_log(client):
    email = f"normal_{uuid.uuid4().hex[:8]}@example.com"
    password = "pass123456"
    await client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Normal User"},
    )

    login = await client.post(
        "/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login.json()["access_token"]

    resp = await client.get(
        "/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
