"""Shared pytest fixtures for all test modules."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import event


# ---------------------------------------------------------------------------
# Basic app fixtures (pre-existing)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# In-memory SQLite session for GST sync tests
# ---------------------------------------------------------------------------

@pytest.fixture
async def async_db_session():
    """
    Provides a throw-away SQLite in-memory AsyncSession.
    Tables are created fresh for each test and dropped afterwards.
    """
    from app.models.database import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # SQLite needs this pragma for FK support
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def seeded_change_log(async_db_session):
    """
    Seeds 55 rows into gst_change_log and returns the session.
    Used by test_admin_changes_endpoint_pagination.
    """
    from app.models.database import GstChangeLog

    rows = [
        GstChangeLog(
            hsn_code=f"{1000 + i:04d}",
            old_rate=5.0,
            new_rate=12.0,
            source="cbic",
            changed_at=datetime.now(timezone.utc),
        )
        for i in range(55)
    ]
    async_db_session.add_all(rows)
    await async_db_session.commit()
    return async_db_session


# ---------------------------------------------------------------------------
# Admin HTTP client with the X-API-Key header pre-set
# ---------------------------------------------------------------------------

@pytest.fixture
async def admin_client(admin_key):
    """AsyncClient authenticated as admin, DB + cache patched."""
    with patch("app.models.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.cache.init_cache", new_callable=AsyncMock):
        from app.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": admin_key},
        ) as c:
            yield c
