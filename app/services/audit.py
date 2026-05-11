from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AuditLog


class EventType:
    PREDICTION_CREATED = "prediction.created"
    GST_RATE_APPLIED = "gst_rate.applied"
    GST_RATE_CHANGED = "gst_rate.changed"
    REVIEW_RESOLVED = "review.resolved"
    USER_ROLE_CHANGED = "user.role_changed"
    CBIC_SCRAPE_FAILED = "cbic.scrape_failed"
    BULK_IMPORT = "bulk.import"


async def log_event(
    session: AsyncSession,
    event_type: str,
    actor_user_id: int | None,
    actor_role: str | None,
    branch_id: UUID | None,
    entity_type: str,
    entity_id: str | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    ip_address: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            branch_id=branch_id,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address,
            metadata_json=metadata,
        )
    )
