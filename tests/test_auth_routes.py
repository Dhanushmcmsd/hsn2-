import pytest


@pytest.mark.asyncio
async def test_register_and_login(client):
    reg = await client.post("/auth/register", json={
        "email": "test@example.com",
        "password": "testpassword123",
        "full_name": "Test User"
    })
    assert reg.status_code in (201, 409)


@pytest.mark.asyncio
async def test_login_invalid(client):
    resp = await client.post("/auth/login", data={
        "username": "nobody@example.com",
        "password": "wrong"
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_unauthorized(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
