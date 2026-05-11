from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import smtplib
from collections import defaultdict
from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
import structlog
from sqlalchemy import select

from app.models.database import User, UserRole, WebhookEndpoint, async_session
from app.services.audit import EventType, log_event
from app.config import settings

# alias so imports that reference AsyncSessionLocal still work
AsyncSessionLocal = async_session

log = structlog.get_logger()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Email notification
# ---------------------------------------------------------------------------

async def notify_gst_rate_change(changed_rates: list[dict]) -> None:
    """Send HTML email alert to BRANCH_MANAGER / REGIONAL_ADMIN / HQ_ADMIN users."""
    if not changed_rates:
        return

    subject = (
        f"GST Rate Change Alert \u2014 {len(changed_rates)} "
        f"HSN codes updated on {date.today()}"
    )
    rows_html = "".join(
        f"<tr><td>{r['hsn_code']}</td>"
        f"<td>{r.get('old_rate', '\u2014')}</td>"
        f"<td>{r['new_rate']}</td>"
        f"<td>{r.get('effective_from', '')}</td></tr>"
        for r in changed_rates
    )
    html_body = f"""
    <h2>GST Rate Changes</h2>
    <table border='1' cellpadding='6'>
      <thead><tr><th>HSN Code</th><th>Old Rate</th>
      <th>New Rate</th><th>Effective From</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>"""

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(
                User.role.in_([
                    UserRole.BRANCH_MANAGER.value,
                    UserRole.REGIONAL_ADMIN.value,
                    UserRole.HQ_ADMIN.value,
                ])
            ).where(User.is_active == True)  # noqa: E712
        )
        recipients = result.scalars().all()
        log.info("notifier.gst_rate_change", recipients=len(recipients), subject=subject)
        try:
            await log_event(
                session=session,
                event_type=EventType.NOTIFICATION_SENT,
                actor_user_id=None,
                actor_role="system",
                branch_id=None,
                entity_type="notification",
                entity_id="gst_rate_change",
                new_value={"subject": subject, "count": len(changed_rates)},
            )
            await session.commit()
        except Exception as exc:
            logger.warning("notifier: audit log failed: %s", exc)

    for user in recipients:
        try:
            await _send_email(user.email, subject, html_body)
            logger.info("GST change notification sent to %s", user.email)
        except Exception as e:
            logger.error("Failed to notify %s: %s", user.email, e)


async def _send_email(to: str, subject: str, html: str) -> None:
    """Send via SendGrid if API key is set, otherwise fall back to SMTP."""
    if settings.SENDGRID_API_KEY:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {settings.SENDGRID_API_KEY}"},
                json={
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": settings.NOTIFICATION_EMAIL_FROM},
                    "subject": subject,
                    "content": [{"type": "text/html", "value": html}],
                },
            )
            resp.raise_for_status()
    else:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.NOTIFICATION_EMAIL_FROM
        msg["To"] = to
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as s:
            if settings.SMTP_USER:
                s.starttls()
                s.login(settings.SMTP_USER, settings.SMTP_PASS)
            s.sendmail(settings.NOTIFICATION_EMAIL_FROM, to, msg.as_string())


# ---------------------------------------------------------------------------
# Webhook delivery
# ---------------------------------------------------------------------------

async def deliver_webhooks(event_type: str, payload: dict) -> None:
    """Fan-out signed webhook delivery to all active matching endpoints."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.is_active == True)  # noqa: E712
        )
        endpoints = result.scalars().all()
        filtered = [ep for ep in endpoints if event_type in (ep.events or [])]

    for ep in filtered:
        await _deliver_with_retry(ep, event_type, payload)

    # audit
    async with AsyncSessionLocal() as session:
        for ep in filtered:
            try:
                await log_event(
                    session=session,
                    event_type=EventType.NOTIFICATION_SENT,
                    actor_user_id=None,
                    actor_role="system",
                    branch_id=None,
                    entity_type="webhook",
                    entity_id=str(ep.id),
                    new_value={"event_type": event_type},
                )
            except Exception:
                pass
        await session.commit()


async def _deliver_with_retry(
    ep: WebhookEndpoint,
    event_type: str,
    payload: dict,
    max_retries: int = 3,
) -> None:
    body = json.dumps({"event": event_type, "data": payload})
    sig = hmac.new(
        ep.secret.encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-HSN-Signature": f"sha256={sig}",
    }
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(ep.url, content=body, headers=headers)
                if resp.status_code < 300:
                    return
        except Exception as e:
            logger.warning("Webhook attempt %d failed: %s", attempt + 1, e)
        await asyncio.sleep(2 ** attempt)
    logger.error(
        "Webhook delivery failed after %d retries: %s", max_retries, ep.url
    )
