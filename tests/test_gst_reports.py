from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import select


async def _create_branch_manager_with_token(client, email: str, branch_id):
    from app.models.database import User, UserRole, async_session

    password = "pass123456"
    await client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Report Manager"},
    )
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalars().first()
        user.role = UserRole.BRANCH_MANAGER.value
        user.branch_id = branch_id
        await db.commit()

    login = await client.post("/auth/login", data={"username": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def _seed_branch_and_predictions(branch_id: uuid.UUID):
    from app.models.database import Branch, Organisation, Prediction, async_session

    async with async_session() as db:
        org = (await db.execute(select(Organisation))).scalars().first()
        if org is None:
            org = Organisation(id=uuid.uuid4(), name=f"Org-{uuid.uuid4().hex[:8]}")
            db.add(org)
            await db.flush()

        branch = (await db.execute(select(Branch).where(Branch.id == branch_id))).scalars().first()
        if branch is None:
            branch = Branch(
                id=branch_id,
                organisation_id=org.id,
                name=f"Test Branch {branch_id.hex[:8]}",
                gstin="32ABCDE1234F1Z5",
            )
            db.add(branch)
            await db.flush()

        now = datetime.now(timezone.utc)
        db.add_all(
            [
                Prediction(
                    request_id=str(uuid.uuid4()),
                    input_text="apple",
                    predicted_hsn="08081000",
                    confidence=0.91,
                    needs_review=False,
                    branch_id=branch_id,
                    created_at=now,
                ),
                Prediction(
                    request_id=str(uuid.uuid4()),
                    input_text="apple big",
                    predicted_hsn="08081000",
                    confidence=0.88,
                    needs_review=False,
                    branch_id=branch_id,
                    created_at=now,
                ),
                Prediction(
                    request_id=str(uuid.uuid4()),
                    input_text="unknown product",
                    predicted_hsn="99999999",
                    confidence=0.45,
                    needs_review=True,
                    branch_id=branch_id,
                    created_at=now,
                ),
            ]
        )
        await db.commit()


@pytest.mark.asyncio
async def test_summary_json_returns_grouped_data(client):
    branch_id = uuid.uuid4()
    await _seed_branch_and_predictions(branch_id)
    token = await _create_branch_manager_with_token(client, f"mgr-{uuid.uuid4().hex[:6]}@example.com", branch_id)

    today = datetime.now(timezone.utc).date().isoformat()
    resp = await client.get(
        f"/reports/gst/summary?branch_id={branch_id}&from_date={today}&to_date={today}&format=json",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    grouped = {row["hsn_code"]: row["transaction_count"] for row in data}
    assert grouped["08081000"] == 2


@pytest.mark.asyncio
async def test_summary_csv_content_type(client):
    branch_id = uuid.uuid4()
    await _seed_branch_and_predictions(branch_id)
    token = await _create_branch_manager_with_token(client, f"mgr-{uuid.uuid4().hex[:6]}@example.com", branch_id)

    today = datetime.now(timezone.utc).date().isoformat()
    resp = await client.get(
        f"/reports/gst/summary?branch_id={branch_id}&from_date={today}&to_date={today}&format=csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")


@pytest.mark.asyncio
async def test_summary_pdf_content_type(client):
    branch_id = uuid.uuid4()
    await _seed_branch_and_predictions(branch_id)
    token = await _create_branch_manager_with_token(client, f"mgr-{uuid.uuid4().hex[:6]}@example.com", branch_id)

    today = datetime.now(timezone.utc).date().isoformat()
    resp = await client.get(
        f"/reports/gst/summary?branch_id={branch_id}&from_date={today}&to_date={today}&format=pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")


@pytest.mark.asyncio
async def test_branch_manager_cannot_see_other_branch(client):
    own_branch_id = uuid.uuid4()
    other_branch_id = uuid.uuid4()
    await _seed_branch_and_predictions(other_branch_id)
    token = await _create_branch_manager_with_token(client, f"mgr-{uuid.uuid4().hex[:6]}@example.com", own_branch_id)

    today = datetime.now(timezone.utc).date().isoformat()
    resp = await client.get(
        f"/reports/gst/summary?branch_id={other_branch_id}&from_date={today}&to_date={today}&format=json",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unclassified_returns_low_confidence(client):
    branch_id = uuid.uuid4()
    await _seed_branch_and_predictions(branch_id)
    token = await _create_branch_manager_with_token(client, f"mgr-{uuid.uuid4().hex[:6]}@example.com", branch_id)

    today = datetime.now(timezone.utc).date().isoformat()
    resp = await client.get(
        f"/reports/gst/unclassified?branch_id={branch_id}&from_date={today}&to_date={today}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows
    assert all(row["confidence"] < 0.7 for row in rows)
