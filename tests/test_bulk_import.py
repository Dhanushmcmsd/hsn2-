"""Tests for Branch 3 — bulk CSV/Excel import and Excel export."""
from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv(rows: list[str]) -> bytes:
    header = "product_description\n"
    return (header + "\n".join(rows)).encode()


def _make_branch_user(branch_id=None):
    from app.models.database import User, UserRole
    u = MagicMock(spec=User)
    u.id = 1
    u.role = UserRole.BRANCH_USER.value
    u.branch_id = branch_id or uuid.uuid4()
    u.is_active = True
    return u


def _mock_match(text, db, top_k=5):
    return [{
        "hsn_code": "01011010",
        "description": "Live horses",
        "score": 0.85,
        "method": "db_match",
        "gst_rate": 0.0,
    }]


def _patched_app():
    return patch("app.models.database.init_db", new_callable=AsyncMock), \
           patch("app.utils.cache.init_cache", new_callable=AsyncMock), \
           patch("app.services.db_matcher.match_query", side_effect=_mock_match), \
           patch("app.routes.bulk._build_gst_fields", new_callable=AsyncMock,
                 return_value={"gst_rate": 0.0, "gst_effective_from": None,
                               "gst_note": None, "gst_effective_to": None}), \
           patch("app.services.audit.log_event", new_callable=AsyncMock)


# ---------------------------------------------------------------------------
# Test 1 — 3-row CSV returns 3 results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_csv_returns_results():
    from app.main import app
    from app.routes.auth import require_role
    from app.models.database import UserRole

    user = _make_branch_user()

    with patch("app.models.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.cache.init_cache", new_callable=AsyncMock), \
         patch("app.services.db_matcher.match_query", side_effect=_mock_match), \
         patch("app.routes.bulk._build_gst_fields", new_callable=AsyncMock,
               return_value={"gst_rate": 0.0, "gst_effective_from": None,
                             "gst_note": None, "gst_effective_to": None}), \
         patch("app.services.audit.log_event", new_callable=AsyncMock), \
         patch("app.routes.bulk.get_db") as mock_db:

        # Fake DB session
        fake_session = AsyncMock()
        fake_session.add = MagicMock()
        fake_session.flush = AsyncMock()
        fake_session.commit = AsyncMock()
        fake_result = MagicMock()
        fake_result.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
        fake_session.execute = AsyncMock(return_value=fake_result)
        mock_db.return_value.__aiter__ = AsyncMock(return_value=iter([fake_session]))

        async def _db_gen():
            yield fake_session

        mock_db.return_value = _db_gen()

        app.dependency_overrides[require_role(
            UserRole.BRANCH_USER, UserRole.BRANCH_MANAGER,
            UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN, UserRole.AUDITOR,
        )] = lambda: user

        csv_bytes = _make_csv(["Rice 5kg", "Wheat flour 1kg", "Sugar 500g"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/predict/bulk/upload",
                files={"file": ("test.csv", csv_bytes, "text/csv")},
            )

        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "import_id" in body
    assert len(body["results"]) == 3


# ---------------------------------------------------------------------------
# Test 2 — 1001-row CSV → 422
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_rejects_over_1000_rows():
    from app.main import app
    from app.routes.auth import require_role
    from app.models.database import UserRole

    user = _make_branch_user()

    rows = [f"Product {i}" for i in range(1001)]
    csv_bytes = _make_csv(rows)

    with patch("app.models.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.cache.init_cache", new_callable=AsyncMock):

        app.dependency_overrides[require_role(
            UserRole.BRANCH_USER, UserRole.BRANCH_MANAGER,
            UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN, UserRole.AUDITOR,
        )] = lambda: user

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/predict/bulk/upload",
                files={"file": ("big.csv", csv_bytes, "text/csv")},
            )

        app.dependency_overrides.clear()

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 3 — CSV without product_description column → 422
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_rejects_missing_column():
    from app.main import app
    from app.routes.auth import require_role
    from app.models.database import UserRole

    user = _make_branch_user()
    csv_bytes = b"name,price\nRice,100\nWheat,80\n"

    with patch("app.models.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.cache.init_cache", new_callable=AsyncMock):

        app.dependency_overrides[require_role(
            UserRole.BRANCH_USER, UserRole.BRANCH_MANAGER,
            UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN, UserRole.AUDITOR,
        )] = lambda: user

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/predict/bulk/upload",
                files={"file": ("bad.csv", csv_bytes, "text/csv")},
            )

        app.dependency_overrides.clear()

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 4 — 6 MB file → 413
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_rejects_oversized_file():
    from app.main import app
    from app.routes.auth import require_role
    from app.models.database import UserRole

    user = _make_branch_user()
    # 6 MB of data
    oversized = b"product_description\n" + b"a" * (6 * 1024 * 1024)

    with patch("app.models.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.cache.init_cache", new_callable=AsyncMock):

        app.dependency_overrides[require_role(
            UserRole.BRANCH_USER, UserRole.BRANCH_MANAGER,
            UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN, UserRole.AUDITOR,
        )] = lambda: user

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/predict/bulk/upload",
                files={"file": ("huge.csv", oversized, "text/csv")},
            )

        app.dependency_overrides.clear()

    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Test 5 — export returns .xlsx content-type
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_returns_xlsx():
    from app.main import app
    from app.routes.auth import require_role
    from app.models.database import UserRole, BulkImport
    from datetime import datetime, timezone

    user = _make_branch_user()
    import_id = str(uuid.uuid4())

    fake_import = MagicMock(spec=BulkImport)
    fake_import.id = import_id
    fake_import.branch_id = user.branch_id
    fake_import.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with patch("app.models.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.cache.init_cache", new_callable=AsyncMock), \
         patch("app.routes.bulk.get_db") as mock_db:

        fake_session = AsyncMock()

        # First execute → BulkImport, second → Predictions, rest → HsnCode lookups
        bulk_result = MagicMock()
        bulk_result.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=fake_import)))

        pred_result = MagicMock()
        pred_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        hsn_result = MagicMock()
        hsn_result.first = MagicMock(return_value=None)

        fake_session.execute = AsyncMock(side_effect=[bulk_result, pred_result, hsn_result])

        async def _db_gen():
            yield fake_session

        mock_db.return_value = _db_gen()

        app.dependency_overrides[require_role(
            UserRole.BRANCH_USER, UserRole.BRANCH_MANAGER,
            UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN, UserRole.AUDITOR,
        )] = lambda: user

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/predict/bulk/{import_id}/export")

        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert "openxmlformats" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Test 6 — branch B user on branch A import → 403
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_forbidden_other_branch():
    from app.main import app
    from app.routes.auth import require_role
    from app.models.database import UserRole, BulkImport
    from datetime import datetime, timezone

    branch_a_id = uuid.uuid4()
    branch_b_id = uuid.uuid4()
    user_b = _make_branch_user(branch_id=branch_b_id)

    import_id = str(uuid.uuid4())
    fake_import = MagicMock(spec=BulkImport)
    fake_import.id = import_id
    fake_import.branch_id = branch_a_id   # belongs to branch A
    fake_import.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with patch("app.models.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.cache.init_cache", new_callable=AsyncMock), \
         patch("app.routes.bulk.get_db") as mock_db:

        fake_session = AsyncMock()
        bulk_result = MagicMock()
        bulk_result.scalars = MagicMock(
            return_value=MagicMock(first=MagicMock(return_value=fake_import))
        )
        fake_session.execute = AsyncMock(return_value=bulk_result)

        async def _db_gen():
            yield fake_session

        mock_db.return_value = _db_gen()

        app.dependency_overrides[require_role(
            UserRole.BRANCH_USER, UserRole.BRANCH_MANAGER,
            UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN, UserRole.AUDITOR,
        )] = lambda: user_b

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/predict/bulk/{import_id}/export")

        app.dependency_overrides.clear()

    assert resp.status_code == 403
