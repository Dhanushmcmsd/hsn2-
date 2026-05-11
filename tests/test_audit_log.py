from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_admin_audit_log_list(admin_client, admin_key, async_db_session):
    from app.main import app
    from app.models.database import AuditLog, get_db

    async_db_session.add(
        AuditLog(
            id=uuid.uuid4(),
            timestamp=datetime.now(timezone.utc),
            actor_user_id=None,
            actor_role="system",
            branch_id=None,
            event_type="test.event",
            entity_type="test_entity",
            entity_id="1",
            old_value={"old": 1},
            new_value={"new": 2},
            ip_address="127.0.0.1",
            metadata_json={"k": "v"},
        )
    )
    await async_db_session.commit()

    async def _override_db():
        yield async_db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        resp = await admin_client.get("/admin/audit-log", headers={"X-API-Key": admin_key})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) >= 1
    assert any(row["event_type"] == "test.event" for row in data)
