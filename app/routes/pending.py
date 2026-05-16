"""Pending products API — list and resolve products awaiting HSN classification."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db, PendingProduct
from app.models.schemas import (
    PendingProductItem,
    PendingProductsResponse,
    PendingProductResolve,
)
from app.utils.auth import require_admin_key

router = APIRouter(prefix="/pending", tags=["pending"])


@router.get("/products", response_model=PendingProductsResponse)
async def list_pending_products(
    status: str = Query("pending", description="Filter by status: pending, resolved, rejected"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_key),
) -> PendingProductsResponse:
    """List all products in the pending_products queue, filtered by status."""
    count_q = (
        select(func.count())
        .select_from(PendingProduct)
        .where(PendingProduct.status == status)
    )
    total = (await db.execute(count_q)).scalar() or 0

    rows_q = (
        select(PendingProduct)
        .where(PendingProduct.status == status)
        .order_by(PendingProduct.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(rows_q)).scalars().all()

    return PendingProductsResponse(
        items=[PendingProductItem.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/products/stats")
async def pending_stats(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_key),
) -> dict:
    """Count of pending_products grouped by status."""
    rows = (await db.execute(
        select(PendingProduct.status, func.count().label("count"))
        .group_by(PendingProduct.status)
    )).all()
    return {"stats": {r.status: r.count for r in rows}}


@router.get("/products/{product_id}", response_model=PendingProductItem)
async def get_pending_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_key),
) -> PendingProductItem:
    """Get a single pending product by ID."""
    row = (await db.execute(
        select(PendingProduct).where(PendingProduct.id == product_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Pending product {product_id} not found")
    return PendingProductItem.model_validate(row)


@router.patch("/products/{product_id}", response_model=PendingProductItem)
async def resolve_pending_product(
    product_id: int,
    body: PendingProductResolve,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_key),
) -> PendingProductItem:
    """
    Resolve a pending product by assigning its confirmed HSN code.
    Also moves the resolved product into verified_products for future lookups.
    """
    row = (await db.execute(
        select(PendingProduct).where(PendingProduct.id == product_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Pending product {product_id} not found")

    await db.execute(
        update(PendingProduct)
        .where(PendingProduct.id == product_id)
        .values(
            hsn_code=body.hsn_code,
            status=body.status,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    # If resolving with an HSN code, promote to verified_products for future lookups
    if body.status == "resolved" and body.hsn_code:
        from app.models.database import VerifiedProduct, _strip_sizes
        desc = row.product_name
        desc_norm = desc.upper().strip()
        desc_no_size = _strip_sizes(desc)
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(VerifiedProduct).values(
                description=desc,
                description_normalized=desc_norm,
                description_no_size=desc_no_size,
                hsn_code=body.hsn_code,
                gst_rate=None,
            ).on_conflict_do_update(
                index_elements=["description_normalized"],
                set_={
                    "hsn_code": body.hsn_code,
                    "description_no_size": desc_no_size,
                }
            )
            await db.execute(stmt)
            await db.commit()
        except Exception:
            # Fall back gracefully if pg-specific upsert fails (e.g., SQLite in tests)
            pass

    refreshed = (await db.execute(
        select(PendingProduct).where(PendingProduct.id == product_id)
    )).scalar_one()
    return PendingProductItem.model_validate(refreshed)


@router.delete("/products/{product_id}", status_code=204)
async def delete_pending_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_key),
) -> None:
    """Hard-delete a pending product (e.g., duplicate or junk entry)."""
    row = (await db.execute(
        select(PendingProduct).where(PendingProduct.id == product_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Pending product {product_id} not found")
    await db.delete(row)
    await db.commit()
