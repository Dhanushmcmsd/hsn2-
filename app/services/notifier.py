from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select

from app.models.database import User, UserRole, WebhookEndpoint, async_session
from app.services.audit import EventType, log_event

log = structlog.get_logger()


async def notify_gst_rate_change(changed_rates: list[dict]) -> None:
    if not changed_rates:
        return
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in changed_rates:
        hsn = str(row.get("hsn_code", ""))
        grouped[hsn[:2]].append(row)
    subject = f"GST Rate Change Alert - {len(changed_rates)} HSN codes updated on {datetime.now(timezone.utc).date().isoformat()}"
    body = {"subject": subject, "groups": grouped}
    try:
        async with async_session() as session:
            users = (
                await session.execute(
                    select(User).where(
                        User.is_active == True,
                        User.role.in_(
                            [
                                UserRole.BRANCH_MANAGER.value,
                                UserRole.REGIONAL_ADMIN.value,
                                UserRole.HQ_ADMIN.value,
                            ]
                        ),
                    )
                )
            ).scalars().all()
            log.info("notifier.gst_rate_change", recipients=len(users), subject=subject)
            await log_event(
                session=session,
                event_type=EventType.NOTIFICATION_SENT,
                actor_user_id=None,
                actor_role="system",
                branch_id=None,
                entity_type="notification",
                entity_id="gst_rate_change",
                new_value=body,
            )
            await session.commit()
    except Exception as exc:
        log.warning("notifier.gst_rate_change_failed", error=str(exc))


async def deliver_webhooks(event_type: str, payload: dict) -> None:
    async with async_session() as session:
        endpoints = (
            await session.execute(select(WebhookEndpoint).where(WebhookEndpoint.is_active == True))
        ).scalars().all()
        filtered = [ep for ep in endpoints if event_type in (ep.events or [])]
        async with httpx.AsyncClient(timeout=10.0) as client:
            for ep in filtered:
                body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
                sig = hmac.new(ep.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
                ok = False
                error = None
                for _ in range(3):
                    try:
                        resp = await client.post(ep.url, content=body, headers={"Content-Type": "application/json", "X-HSN-Signature": sig})
                        if 200 <= resp.status_code < 300:
                            ok = True
                            break
                    except Exception as exc:
                        error = str(exc)
                await log_event(
                    session=session,
                    event_type=EventType.NOTIFICATION_SENT,
                    actor_user_id=None,
                    actor_role="system",
                    branch_id=None,
                    entity_type="webhook",
                    entity_id=str(ep.id),
                    new_value={"event_type": event_type, "delivered": ok, "error": error},
                )
        await session.commit()
