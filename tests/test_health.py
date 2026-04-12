import pytest


@pytest.mark.asyncio
async def test_health_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_health_detailed(client):
    resp = await client.get("/health/detailed")
    assert resp.status_code == 200
    assert "version" in resp.json()
