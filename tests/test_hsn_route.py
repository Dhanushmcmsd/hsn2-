from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.models.database import get_db
from app.routes import hsn as hsn_route


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeDB:
    def __init__(self, *, row, available_columns: set[str]):
        self.row = row
        self.available_columns = available_columns

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "FROM hsn_codes LIMIT 0" in sql:
            column = sql.split("SELECT ", 1)[1].split(" FROM", 1)[0].strip()
            if column in self.available_columns:
                return _FakeResult()
            raise OperationalError(sql, params, Exception("missing column"))
        if "FROM hsn_codes h" in sql:
            if params and params.get("code") == self.row.hsn_code:
                return _FakeResult(self.row)
            return _FakeResult(None)
        raise AssertionError(f"Unexpected SQL: {sql}")


@pytest.mark.asyncio
async def test_get_hsn_by_code_builds_full_description(client):
    hsn_route._HSN_COLUMN_CACHE.clear()
    fake_row = SimpleNamespace(
        hsn_code="62041200",
        description="of cotton",
        parent_heading_desc="Women's or girls' suits, jackets",
        cbic_description=None,
        gst_rate=12,
        category="Apparel",
        section=None,
    )
    fake_db = _FakeDB(
        row=fake_row,
        available_columns={"parent_heading_desc", "category", "gst_rate"},
    )

    async def override_get_db():
        yield fake_db

    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.routes.hsn.get_cache", new_callable=AsyncMock, return_value=None), \
             patch("app.routes.hsn.set_cache", new_callable=AsyncMock):
            resp = await client.get("/hsn/62041200")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["hsn_code"] == "62041200"
    assert data["description"] == "of cotton"
    assert data["full_description"] == "Women's or girls' suits, jackets — of cotton"
    assert data["chapter"] == "62"
    assert data["heading"] == "6204"
    assert data["category"] == "Apparel"


@pytest.mark.asyncio
async def test_get_hsn_by_code_falls_back_without_optional_columns(client):
    hsn_route._HSN_COLUMN_CACHE.clear()
    fake_row = SimpleNamespace(
        hsn_code="19053100",
        description="Sweet biscuits",
        parent_heading_desc=None,
        cbic_description=None,
        gst_rate=0,
        category=None,
        section=None,
    )
    fake_db = _FakeDB(row=fake_row, available_columns=set())

    async def override_get_db():
        yield fake_db

    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.routes.hsn.get_cache", new_callable=AsyncMock, return_value=None), \
             patch("app.routes.hsn.set_cache", new_callable=AsyncMock):
            resp = await client.get("/hsn/19053100")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["full_description"] == "Sweet biscuits"
    assert data["chapter"] == "19"
    assert data["heading"] == "1905"
    assert data["category"] is None
