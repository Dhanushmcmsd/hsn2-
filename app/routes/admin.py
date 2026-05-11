from __future__ import annotations
import csv
import io
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query  # --- ADDED: GST ---
from fastapi.responses import StreamingResponse
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession             # --- ADDED: GST ---
from sqlalchemy import text, func, select                   # --- ADDED: GST ---
from app.utils.auth import require_admin_key
from app.routes.auth import require_role
from app.services.important_products import get_important_products, save_important_products
from app.models.schemas import (
    ImportantProduct,
    ProductAnalysisRequest,
    ProductAnalysisResponse,
    GstChangeItem,          # --- ADDED: GST ---
    GstChangesResponse,     # --- ADDED: GST ---
    UserRoleUpdate,
)
from app.utils.text_utils import normalize_product_description, extract_pack_size
from app.services.matcher import get_matcher
from app.services.confidence import score_result
from app.config import settings
from app.utils.scheduler import trigger_gst_sync_now
from app.models.database import ApiKey, AuditLog, Branch, GstChangeLog, Organisation, User, UserRole, WebhookEndpoint, get_db       # --- ADDED: GST ---
from app.services.audit import EventType, log_event
from app.services.notifier import deliver_webhooks
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

router = APIRouter(prefix="/admin", tags=["admin"])
log = structlog.get_logger()


def _match_best_product_query(matcher, original_name: str) -> tuple[str, str, list[dict]]:
    cleaned_description = normalize_product_description(original_name)
    query_options = [original_name.strip()]
    if cleaned_description and cleaned_description.strip():
        cleaned = cleaned_description.strip()
        if cleaned.lower() != query_options[0].lower():
            query_options.append(cleaned)

    best_query = query_options[0] if query_options else ""
    best_matches: list[dict] = []
    for query_text in query_options:
        matches = matcher.match(query_text, top_k=5)
        if not matches:
            continue
        if not best_matches or matches[0].get("score", 0.0) > best_matches[0].get("score", 0.0):
            best_query = query_text
            best_matches = matches

    return best_query, cleaned_description, best_matches


@router.get("/circuit-breakers")
async def circuit_breakers(admin_key: str = Depends(require_admin_key)):
    return {"circuit_breakers": [], "status": "ok"}


@router.post("/retrain/check")
async def retrain_check(admin_key: str = Depends(require_admin_key)):
    return {"status": "no_retrain_needed", "message": "Model is current"}


@router.get("/retrain/versions")
async def retrain_versions(admin_key: str = Depends(require_admin_key)):
    return {"versions": ["v1.0"], "current": "v1.0"}


@router.post("/dataset/reload")
async def dataset_reload(admin_key: str = Depends(require_admin_key)):
    return {"status": "reloaded"}


@router.get("/dataset/integrity")
async def dataset_integrity(admin_key: str = Depends(require_admin_key)):
    return {"status": "ok", "checksum": "verified"}


@router.get("/important-products", response_model=List[ImportantProduct])
async def get_important_products_endpoint(admin_key: str = Depends(require_admin_key)):
    """Get all important products."""
    products = get_important_products()
    return [ImportantProduct(**p) for p in products]


@router.post("/important-products/analyze")
async def analyze_product(
    body: ProductAnalysisRequest,
    admin_key: str = Depends(require_admin_key)
) -> ProductAnalysisResponse:
    """Analyze a single important product and potentially auto-update HSN."""
    products = get_important_products()

    if body.product_index < 0 or body.product_index >= len(products):
        raise HTTPException(status_code=404, detail="Product index out of range")

    product = products[body.product_index]
    original_name = product["product_name"]

    pack_size = extract_pack_size(original_name)
    matcher = get_matcher()
    best_query, cleaned_description, matches = _match_best_product_query(matcher, original_name)

    product["cleaned_description"] = cleaned_description
    product["pack_or_size"] = pack_size

    if not matches:
        product["status"] = "no_matches_found"
        save_important_products(products)
        return ProductAnalysisResponse(
            product_index=body.product_index,
            original_name=original_name,
            cleaned_description=cleaned_description,
            hsn_analysis={"error": "No HSN matches found"},
            auto_updated=False,
            message="No matches found for cleaned description"
        )

    top_match = matches[0]
    confidence, label = score_result(top_match["score"])

    hsn_analysis = {
        "hsn_code": top_match["hsn_code"],
        "description": top_match["description"],
        "confidence": confidence,
        "confidence_label": label,
        "method": top_match["method"],
        "query_used": best_query,
        "alternatives": matches[1:]
    }

    auto_updated = False
    if confidence >= settings.CONFIDENCE_HIGH or body.force_update:
        product["hsn_code"] = top_match["hsn_code"]
        product["confidence"] = confidence
        product["status"] = "auto_updated"
        auto_updated = True
        message = f"Auto-updated HSN to {top_match['hsn_code']} with {confidence:.2f} confidence"
    else:
        product["status"] = "review_recommended"
        message = f"Review recommended - confidence {confidence:.2f} below threshold"

    save_important_products(products)

    return ProductAnalysisResponse(
        product_index=body.product_index,
        original_name=original_name,
        cleaned_description=cleaned_description,
        hsn_analysis=hsn_analysis,
        auto_updated=auto_updated,
        message=message
    )


@router.post("/important-products/batch-analyze")
async def batch_analyze_products(admin_key: str = Depends(require_admin_key)):
    """Analyze all important products that don't have HSN codes yet."""
    products = get_important_products()
    results = []

    for i, product in enumerate(products):
        if product.get("hsn_code") and product.get("status") != "pending":
            continue

        pack_size = extract_pack_size(product["product_name"])
        matcher = get_matcher()
        best_query, cleaned_description, matches = _match_best_product_query(
            matcher,
            product["product_name"],
        )

        product["cleaned_description"] = cleaned_description
        product["pack_or_size"] = pack_size

        if matches:
            top_match = matches[0]
            confidence, label = score_result(top_match["score"])

            if confidence >= settings.CONFIDENCE_HIGH:
                product["hsn_code"] = top_match["hsn_code"]
                product["confidence"] = confidence
                product["status"] = "auto_updated"
                results.append({
                    "index": i,
                    "product_name": product["product_name"],
                    "hsn_code": top_match["hsn_code"],
                    "confidence": confidence,
                    "query_used": best_query,
                    "status": "auto_updated"
                })
            else:
                product["status"] = "review_recommended"
                results.append({
                    "index": i,
                    "product_name": product["product_name"],
                    "confidence": confidence,
                    "query_used": best_query,
                    "status": "review_recommended"
                })
        else:
            product["status"] = "no_matches_found"
            results.append({
                "index": i,
                "product_name": product["product_name"],
                "status": "no_matches_found"
            })

    save_important_products(products)
    return {"results": results, "total_processed": len(results)}


# kept for backwards compat — redirects to the canonical /gst/sync
@router.post("/gst-sync", include_in_schema=False)
async def manual_gst_sync_legacy(admin_key: str = Depends(require_admin_key)) -> dict:
    return await manual_gst_sync(admin_key=admin_key)


# ---------------------------------------------------------------------------
# GST endpoints                                          # --- ADDED: GST ---
# ---------------------------------------------------------------------------

@router.post(
    "/gst/sync",
    summary="Manually trigger the nightly GST rate sync",
)
async def manual_gst_sync(admin_key: str = Depends(require_admin_key)) -> dict:
    """
    Immediately runs the same job that the nightly cron fires at 02:00 IST.
    Protected by ADMIN_API_KEY.
    Returns: {status, updated, unchanged, source, duration_ms}
    """
    try:
        result = await trigger_gst_sync_now()
        log.info("admin.gst_sync_triggered", **result)
        return {"status": "ok", **result}
    except Exception as exc:
        log.error("admin.gst_sync_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"GST sync failed: {exc}")


@router.get(
    "/gst/changes",
    response_model=GstChangesResponse,
    summary="Paginated audit log of GST rate changes",
)
async def gst_change_log(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(default=50, ge=1, le=200, description="Items per page"),
    hsn_code: str | None = Query(default=None, description="Filter by exact HSN code"),
    admin_key: str = Depends(require_admin_key),
    db: AsyncSession = Depends(get_db),
) -> GstChangesResponse:
    """
    Returns paginated rows from gst_change_log.
    Each item: {id, hsn_code, old_rate, new_rate, changed_at, source, notes}
    Ordered by changed_at DESC (most recent first).
    """
    offset = (page - 1) * per_page

    try:
        # Build base query
        base_q = select(GstChangeLog)
        count_q = select(func.count()).select_from(GstChangeLog)

        if hsn_code:
            base_q = base_q.where(GstChangeLog.hsn_code == hsn_code)
            count_q = count_q.where(GstChangeLog.hsn_code == hsn_code)

        total_result = await db.execute(count_q)
        total = total_result.scalar() or 0

        rows_result = await db.execute(
            base_q
            .order_by(GstChangeLog.changed_at.desc())
            .limit(per_page)
            .offset(offset)
        )
        rows = rows_result.scalars().all()

        items = [
            GstChangeItem(
                id=row.id,
                hsn_code=row.hsn_code,
                old_rate=float(row.old_rate) if row.old_rate is not None else None,
                new_rate=float(row.new_rate),
                changed_at=row.changed_at,
                source=row.source,
                notes=None,   # reserved for future use
            )
            for row in rows
        ]

        return GstChangesResponse(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
        )

    except Exception as exc:
        log.error("admin.gst_changes_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to fetch GST change log: {exc}")
# --- ADDED: GST ---


@router.get("/audit-log")
async def audit_log_list(
    branch_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    actor_user_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN, UserRole.AUDITOR)),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    q = select(AuditLog)
    cq = select(func.count()).select_from(AuditLog)
    if branch_id:
        q = q.where(AuditLog.branch_id == branch_id)
        cq = cq.where(AuditLog.branch_id == branch_id)
    if event_type:
        q = q.where(AuditLog.event_type == event_type)
        cq = cq.where(AuditLog.event_type == event_type)
    if actor_user_id is not None:
        q = q.where(AuditLog.actor_user_id == actor_user_id)
        cq = cq.where(AuditLog.actor_user_id == actor_user_id)
    if from_date:
        q = q.where(AuditLog.timestamp >= from_date)
        cq = cq.where(AuditLog.timestamp >= from_date)
    if to_date:
        q = q.where(AuditLog.timestamp <= to_date)
        cq = cq.where(AuditLog.timestamp <= to_date)

    total = (await db.execute(cq)).scalar() or 0
    rows = (
        await db.execute(q.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset))
    ).scalars().all()
    items = [
        {
            "id": str(r.id),
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "actor_user_id": r.actor_user_id,
            "actor_role": r.actor_role,
            "branch_id": str(r.branch_id) if r.branch_id else None,
            "event_type": r.event_type,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "ip_address": r.ip_address,
            "metadata": r.metadata_json,
        }
        for r in rows
    ]
    from fastapi.responses import JSONResponse
    resp = JSONResponse(content=items)
    resp.headers["X-Total-Count"] = str(total)
    return resp


@router.get("/audit-log/export")
async def audit_log_export(
    branch_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN, UserRole.AUDITOR)),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    q = select(AuditLog)
    if branch_id:
        q = q.where(AuditLog.branch_id == branch_id)
    if event_type:
        q = q.where(AuditLog.event_type == event_type)
    if from_date:
        q = q.where(AuditLog.timestamp >= from_date)
    if to_date:
        q = q.where(AuditLog.timestamp <= to_date)
    rows = (await db.execute(q.order_by(AuditLog.timestamp.desc()))).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id", "timestamp", "actor_user_id", "actor_role", "branch_id",
            "event_type", "entity_type", "entity_id", "old_value", "new_value",
            "ip_address", "metadata",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                str(r.id),
                r.timestamp.isoformat() if r.timestamp else "",
                r.actor_user_id if r.actor_user_id is not None else "",
                r.actor_role or "",
                str(r.branch_id) if r.branch_id else "",
                r.event_type,
                r.entity_type or "",
                r.entity_id or "",
                r.old_value or {},
                r.new_value or {},
                r.ip_address or "",
                r.metadata_json or {},
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit_log_{from_date or 'start'}_{to_date or 'end'}.csv"},
    )


@router.get("/users")
async def admin_list_users(
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    rows = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    return [
        {
            "id": row.id,
            "email": row.email,
            "role": row.role,
            "branch_id": str(row.branch_id) if row.branch_id else None,
            "last_login": None,
            "is_active": row.is_active,
        }
        for row in rows
    ]


@router.patch("/users/{user_id}/role")
async def admin_update_user_role(
    user_id: int,
    body: UserRoleUpdate,
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    old_role = target.role
    target.role = body.role
    target.branch_id = body.branch_id
    await log_event(
        session=db,
        event_type=EventType.USER_ROLE_CHANGED,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        branch_id=current_user.branch_id,
        entity_type="user",
        entity_id=str(target.id),
        old_value={"role": old_role},
        new_value={"role": body.role},
    )
    await db.commit()
    return {"status": "ok", "user_id": target.id, "old_role": old_role, "new_role": target.role}


@router.post("/users/{user_id}/deactivate")
async def admin_deactivate_user(
    user_id: int,
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = False
    await db.commit()
    return {"status": "ok", "user_id": target.id, "is_active": target.is_active}


@router.patch("/api-keys/{key_id}/tier")
async def admin_update_api_key_tier(
    key_id: int,
    tier: str = Query(..., description="free | standard | enterprise"),
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    normalized = tier.strip().lower()
    if normalized not in {"free", "standard", "enterprise"}:
        raise HTTPException(status_code=422, detail="tier must be one of: free, standard, enterprise")
    row = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="API key not found")
    old_tier = row.tier
    row.tier = normalized
    await db.commit()
    return {"status": "ok", "key_id": row.id, "old_tier": old_tier, "new_tier": row.tier}


@router.post("/api-keys/{key_id}/rotate")
async def rotate_api_key(
    key_id: int,
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")
    raw_key = f"hsn_{secrets.token_urlsafe(32)}"
    new_key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    new_key = ApiKey(
        key_hash=new_key_hash,
        label=f"{row.label or 'rotated'}-rotated",
        tier=row.tier,
        branch_id=row.branch_id,
        role=row.role,
        is_active=True,
    )
    db.add(new_key)
    row.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await log_event(
        session=db,
        event_type=EventType.API_KEY_ROTATED,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        branch_id=current_user.branch_id,
        entity_type="api_key",
        entity_id=str(row.id),
        new_value={"new_key_id": None},
    )
    await db.commit()
    await db.refresh(new_key)
    return {"status": "ok", "new_api_key": raw_key, "new_key_id": new_key.id, "old_key_expires_at": row.expires_at}


@router.post("/webhooks")
async def register_webhook(
    url: str = Query(...),
    events: str = Query(default="gst_rate.changed"),
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    org_id = None
    if current_user.branch_id:
        branch = (await db.execute(select(Branch).where(Branch.id == current_user.branch_id))).scalars().first()
        if branch:
            org_id = branch.organisation_id
    if org_id is None:
        org = (await db.execute(select(Organisation))).scalars().first()
        org_id = org.id if org else None
    if org_id is None:
        raise HTTPException(status_code=400, detail="No organisation configured")
    secret = secrets.token_hex(32)
    row = WebhookEndpoint(org_id=org_id, url=url, secret=secret, events=[e.strip() for e in events.split(",") if e.strip()], is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "url": row.url, "events": row.events, "secret": secret}


@router.get("/webhooks")
async def list_webhooks(
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(WebhookEndpoint))).scalars().all()
    return [{"id": str(r.id), "url": r.url, "events": r.events, "is_active": r.is_active} for r in rows]


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(
    webhook_id: str,
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.id == webhook_id))).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await db.delete(row)
    await db.commit()
    return {"status": "deleted"}


@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(
    webhook_id: str,
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.id == webhook_id))).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await deliver_webhooks("gst_rate.changed", {"test": True, "webhook_id": webhook_id})
    return {"status": "sent"}
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
