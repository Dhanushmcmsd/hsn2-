from __future__ import annotations
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch


@pytest.fixture
async def client():
    with patch("app.models.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.cache.init_cache", new_callable=AsyncMock):
        from app.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.fixture
def api_key():
    return "dev-api-key"


@pytest.fixture
def admin_key():
    return "dev-admin-key"
