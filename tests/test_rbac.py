from __future__ import annotations

import pytest
from sqlalchemy import select


async def _register_and_login(client, email: str, password: str = "pass123456"):
    await client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": email.split("@")[0]},
    )
    resp = await client.post(
        "/auth/login",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_rbac_access_controls(client):
    from app.models.database import User, UserRole, async_session

    branch_user_email = "rbac_branch@example.com"
    hq_admin_email = "rbac_hq@example.com"
    auditor_email = "rbac_auditor@example.com"

    await _register_and_login(client, branch_user_email)
    await _register_and_login(client, hq_admin_email)
    await _register_and_login(client, auditor_email)

    async with async_session() as db:
        users = {
            u.email: u
            for u in (await db.execute(select(User))).scalars().all()
            if u.email in {branch_user_email, hq_admin_email, auditor_email}
        }
        users[branch_user_email].role = UserRole.BRANCH_USER.value
        users[hq_admin_email].role = UserRole.HQ_ADMIN.value
        users[auditor_email].role = UserRole.AUDITOR.value
        await db.commit()

        target_user_id = users[branch_user_email].id

    branch_token = await _register_and_login(client, branch_user_email)
    hq_token = await _register_and_login(client, hq_admin_email)
    auditor_token = await _register_and_login(client, auditor_email)

    # branch user cannot access /admin/users
    branch_resp = await client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {branch_token}"},
    )
    assert branch_resp.status_code == 403

    # HQ admin can change roles
    hq_resp = await client.patch(
        f"/admin/users/{target_user_id}/role",
        headers={"Authorization": f"Bearer {hq_token}"},
        json={"role": UserRole.BRANCH_MANAGER.value},
    )
    assert hq_resp.status_code == 200, hq_resp.text
    assert hq_resp.json()["new_role"] == UserRole.BRANCH_MANAGER.value

    # auditor can GET /review/pending
    auditor_get = await client.get(
        "/review/pending",
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert auditor_get.status_code == 200, auditor_get.text

    # auditor cannot POST /review/resolve
    auditor_post = await client.post(
        "/review/resolve",
        headers={"Authorization": f"Bearer {auditor_token}"},
        json={"request_id": "does-not-exist", "corrected_hsn": "0101"},
    )
    assert auditor_post.status_code == 403
