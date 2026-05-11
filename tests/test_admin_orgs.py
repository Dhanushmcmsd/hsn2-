from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_admin_orgs_create_list_and_soft_delete(admin_client, admin_key):
    org_name = f"Acme HQ {uuid.uuid4().hex[:8]}"
    create_org = await admin_client.post(
        "/admin/orgs",
        headers={"X-API-Key": admin_key},
        json={"name": org_name, "gstin_prefix": "32"},
    )
    assert create_org.status_code == 200, create_org.text
    org_id = create_org.json()["id"]

    create_branch = await admin_client.post(
        f"/admin/orgs/{org_id}/branches",
        headers={"X-API-Key": admin_key},
        json={"name": "Kochi Branch", "city": "Kochi", "state_code": "KL", "gstin": "32ABCDE1234F1Z5"},
    )
    assert create_branch.status_code == 200, create_branch.text
    branch_id = create_branch.json()["id"]

    list_orgs = await admin_client.get("/admin/orgs", headers={"X-API-Key": admin_key})
    assert list_orgs.status_code == 200
    assert any(item["name"] == org_name for item in list_orgs.json())

    list_branches = await admin_client.get(
        f"/admin/orgs/{org_id}/branches",
        headers={"X-API-Key": admin_key},
    )
    assert list_branches.status_code == 200
    assert any(item["name"] == "Kochi Branch" for item in list_branches.json())

    delete_branch = await admin_client.delete(
        f"/admin/branches/{branch_id}",
        headers={"X-API-Key": admin_key},
    )
    assert delete_branch.status_code == 200
    assert delete_branch.json()["is_active"] is False
