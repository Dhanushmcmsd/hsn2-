"""Tests for GST rate-change notifications and webhook delivery."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(role: str) -> MagicMock:
    u = MagicMock()
    u.email = f"{role}@example.com"
    u.role = role
    u.is_active = True
    return u


def _make_endpoint(events: list[str]) -> MagicMock:
    ep = MagicMock()
    ep.id = uuid.uuid4()
    ep.url = "https://example.com/hook"
    ep.secret = "testsecret"
    ep.events = events
    ep.is_active = True
    return ep


# ---------------------------------------------------------------------------
# test_notify_sends_to_managers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_sends_to_managers():
    """_send_email should be called once per eligible manager/admin user."""
    users = [
        _make_user("branch_manager"),
        _make_user("hq_admin"),
        _make_user("branch_user"),   # should NOT receive email
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        u for u in users if u.role in ("branch_manager", "hq_admin")
    ]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_factory = MagicMock(return_value=mock_session)

    changed_rates = [
        {"hsn_code": "0101", "old_rate": 5.0, "new_rate": 12.0, "effective_from": "2026-01-01"},
    ]

    with patch("app.services.notifier.AsyncSessionLocal", mock_session_factory), \
         patch("app.services.notifier._send_email", new_callable=AsyncMock) as mock_send, \
         patch("app.services.notifier.log_event", new_callable=AsyncMock):
        from app.services.notifier import notify_gst_rate_change
        await notify_gst_rate_change(changed_rates)

    assert mock_send.call_count == 2
    called_emails = {call.args[0] for call in mock_send.call_args_list}
    assert "branch_manager@example.com" in called_emails
    assert "hq_admin@example.com" in called_emails


# ---------------------------------------------------------------------------
# test_empty_changes_skips_notify
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_changes_skips_notify():
    """Empty changed_rates list must not trigger any email."""
    with patch("app.services.notifier._send_email", new_callable=AsyncMock) as mock_send:
        from app.services.notifier import notify_gst_rate_change
        await notify_gst_rate_change([])

    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# test_webhook_signature_header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_signature_header():
    """X-HSN-Signature must be present and equal to HMAC-SHA256 of the body."""
    ep = _make_endpoint(["gst_rate.changed"])
    payload = {"changes": [{"hsn_code": "0101", "new_rate": 12}]}

    captured_headers: dict = {}
    captured_body: str = ""

    async def fake_post(url, *, content, headers, **kwargs):
        nonlocal captured_headers, captured_body
        captured_headers = dict(headers)
        captured_body = content
        resp = MagicMock()
        resp.status_code = 200
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=fake_post)

    with patch("app.services.notifier.httpx.AsyncClient", return_value=mock_client):
        from app.services.notifier import _deliver_with_retry
        await _deliver_with_retry(ep, "gst_rate.changed", payload)

    assert "X-HSN-Signature" in captured_headers
    sig_header = captured_headers["X-HSN-Signature"]
    assert sig_header.startswith("sha256=")

    body_str = captured_body if isinstance(captured_body, str) else captured_body.decode()
    expected_sig = "sha256=" + hmac.new(
        ep.secret.encode(), body_str.encode(), hashlib.sha256
    ).hexdigest()
    assert sig_header == expected_sig


# ---------------------------------------------------------------------------
# test_webhook_retries_on_500
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_retries_on_500():
    """Delivery should retry up to max_retries times; succeed on 3rd attempt."""
    ep = _make_endpoint(["gst_rate.changed"])
    payload = {"changes": []}

    call_count = 0

    async def flaky_post(url, *, content, headers, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 200 if call_count >= 3 else 500
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=flaky_post)

    with patch("app.services.notifier.httpx.AsyncClient", return_value=mock_client), \
         patch("app.services.notifier.asyncio.sleep", new_callable=AsyncMock):
        from app.services.notifier import _deliver_with_retry
        await _deliver_with_retry(ep, "gst_rate.changed", payload, max_retries=3)

    assert call_count == 3
