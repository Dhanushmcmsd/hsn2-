from __future__ import annotations
import csv                                   # --- ADDED: GST ---
import hashlib
import inspect
import io                                    # --- ADDED: GST ---
import time
import uuid
from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse  # --- ADDED: GST ---
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select                # --- ADDED: GST ---

from app.models.database import get_db, Prediction, VerifiedProduct, HsnCode  # --- ADDED: GST ---
from app.models.gst_rate_history import GSTRateHistory
from app.models.schemas import PredictRequest, PredictResponse
from app.services.matcher import get_matcher, strip_sizes
from app.services.kerala_search import expand_kerala_query
from app.services.db_matcher import match_query
from app.services.confidence import score_result
from app.utils.auth import require_api_key
from app.utils.cache import get_cache, set_cache
from app.utils.rate_limit import check_rate_limit
# --- ADDED: GST ---
from app.services.gst_fetcher import fetch_gst_rate_for_hsn
# --- ADDED: GST ---

router = APIRouter(tags=["predict"])
log = structlog.get_logger()


async def _scalar_one_or_none(result):
    value = result.scalar_one_or_none()
    if inspect.isawaitable(value):
        value = await value
    return value


def _is_verified_product_match(candidate) -> bool:
    return isinstance(getattr(candidate, "hsn_code", None), str) and isinstance(
        getattr(candidate, "description", None), str
    )


# --- ADDED: GST ---
async def _build_gst_fields(hsn_code: str, db: AsyncSession) -> dict:
    """
    Look up GST rate for a predicted HSN code.
    Priority: hsn_codes.gst_rate_numeric (DB, already synced) → gst_fetcher live lookup.
    Returns dict with keys: gst_rate, gst_note, gst_effective_from, gst_effective_to
    """
    gst_rate = None
    gst_note = None
    gst_effective_from = None
    gst_effective_to = None

    try:
        # Fast path: already in DB from nightly sync
        result = await db.execute(
            select(HsnCode.gst_rate_numeric, HsnCode.gst_effective_from, HsnCode.gst_effective_to)
            .where(HsnCode.hsn_code == hsn_code)
        )
        row = result.fetchone()
        if row and row.gst_rate_numeric is not None:
            gst_rate = float(row.gst_rate_numeric)
            eff_from = row.gst_effective_from
            eff_to = row.gst_effective_to
            if gst_rate is not None and eff_from:
                gst_note = f"GST {gst_rate:.0f}% \u2014 effective {eff_from:%d-%b-%Y}"
                gst_effective_from = eff_from.isoformat()
            elif gst_rate is not None:
                gst_note = f"GST {gst_rate:.0f}%"
            gst_effective_to = eff_to.isoformat() if eff_to else None
            return {
                "gst_rate": gst_rate,
                "gst_note": gst_note,
                "gst_effective_from": gst_effective_from,
                "gst_effective_to": gst_effective_to,
            }
    except Exception as exc:
        log.debug("predict.gst_db_lookup_failed", hsn=hsn_code, error=str(exc))

    # Slow path: live gst_fetcher lookup (uses Redis cache + 3-layer fallback)
    try:
        fetched = await fetch_gst_rate_for_hsn(hsn_code)
        if fetched:
            gst_rate = float(fetched["rate"])
            eff_from = fetched["effective_from"]
            if gst_rate is not None and eff_from:
                gst_note = f"GST {gst_rate:.0f}% \u2014 effective {eff_from:%d-%b-%Y}"
                gst_effective_from = eff_from.isoformat()
            elif gst_rate is not None:
                gst_note = f"GST {gst_rate:.0f}%"
    except Exception as exc:
        log.debug("predict.gst_fetcher_lookup_failed", hsn=hsn_code, error=str(exc))

    return {
        "gst_rate": gst_rate,
        "gst_note": gst_note,
        "gst_effective_from": gst_effective_from,
        "gst_effective_to": gst_effective_to,
    }
# --- ADDED: GST ---


async def get_gst_dates(hsn_code: str, db: AsyncSession) -> dict:
    """
    Query GSTRateHistory for the currently-active rate window for a given HSN code.

    Conditions:
      - hsn_code matches exactly
      - effective_from <= today
      - effective_to IS NULL  OR  effective_to >= today  (NULL = currently active)

    Returns the most recently started window (ORDER BY effective_from DESC, LIMIT 1).

    Returns
    -------
    dict with keys:
        gst_effective_from : str | None   (ISO 8601 date, e.g. "2024-04-01")
        gst_effective_to   : str | None   (ISO 8601 date, or None when open-ended)
        gst_note           : str | None   (human-readable summary for the response)
    """
    try:
        today = date.today()
        result = await db.execute(
            select(GSTRateHistory)
            .where(
                GSTRateHistory.hsn_code == hsn_code,
                GSTRateHistory.effective_from <= today,
                (
                    GSTRateHistory.effective_to.is_(None)
                    | (GSTRateHistory.effective_to >= today)
                ),
            )
            .order_by(GSTRateHistory.effective_from.desc())
            .limit(1)
        )
        row: GSTRateHistory | None = result.scalars().first()

        if row is None:
            return {"gst_effective_from": None, "gst_effective_to": None, "gst_note": None}

        eff_from_str = row.effective_from.isoformat() if row.effective_from else None
        eff_to_str = row.effective_to.isoformat() if row.effective_to else None

        if eff_from_str:
            gst_note = (
                f"GST {row.gst_rate:.0f}% — effective {row.effective_from:%d-%b-%Y}"
                + (f" to {row.effective_to:%d-%b-%Y}" if row.effective_to else " (currently active)")
            )
        else:
            gst_note = f"GST {row.gst_rate:.0f}%" if row.gst_rate is not None else None

        return {
            "gst_effective_from": eff_from_str,
            "gst_effective_to": eff_to_str,
            "gst_note": gst_note,
        }

    except Exception as exc:
        log.debug("predict.get_gst_dates_failed", hsn=hsn_code, error=str(exc))
        return {"gst_effective_from": None, "gst_effective_to": None, "gst_note": None}


@router.post("/predict", response_model=PredictResponse)
async def predict(
    body: PredictRequest,
    request: Request,
    api_key: str = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    await check_rate_limit(api_key)
    request_id = str(uuid.uuid4())

    cache_key = f"predict:{body.text.strip().lower()}"
    cached = await get_cache(cache_key)
    if cached:
        log.info("predict.cache_hit", text=body.text[:50])
        return PredictResponse(**cached)

    start = time.perf_counter()

    # Pass 0: Check verified_products for exact / no-size match when available
    verified = None
    try:
        verified_query = select(VerifiedProduct).where(
            VerifiedProduct.description_normalized == body.text.upper().strip()
        )
        verified_result = await db.execute(verified_query)
        verified = await _scalar_one_or_none(verified_result)
    except Exception as exc:
        log.info("predict.verified_exact_unavailable", error=str(exc))

    if _is_verified_product_match(verified):
        top = {
            "hsn_code": verified.hsn_code,
            "description": verified.description,
            "gst_rate": float(verified.gst_rate or 0) if verified.gst_rate else None,
            "score": 1.0,
            "method": "verified_exact",
        }
        alternatives = []
        confidence, label = score_result(1.0)
        needs_review = False
        elapsed = (time.perf_counter() - start) * 1000
    else:
        verified = None
        try:
            kerala_expanded = expand_kerala_query(body.text)
            if kerala_expanded != body.text.upper().strip():
                verified_query2 = select(VerifiedProduct).where(
                    VerifiedProduct.description_normalized == kerala_expanded
                )
                verified_result2 = await db.execute(verified_query2)
                verified2 = await _scalar_one_or_none(verified_result2)
                if _is_verified_product_match(verified2):
                    top = {
                        "hsn_code": verified2.hsn_code,
                        "description": verified2.description,
                        "gst_rate": float(verified2.gst_rate or 0) if verified2.gst_rate else None,
                        "score": 0.92,
                        "method": "verified_kerala_expanded",
                    }
                    alternatives = []
                    confidence, label = score_result(0.92)
                    needs_review = False
                    elapsed = (time.perf_counter() - start) * 1000
                    verified = verified2
        except Exception as exc:
            log.info("predict.verified_kerala_expanded_unavailable", error=str(exc))

    if not _is_verified_product_match(verified):
        verified = None
        try:
            verified_no_size_query = select(VerifiedProduct).where(
                VerifiedProduct.description_no_size == strip_sizes(body.text)
            )
            verified_no_size_result = await db.execute(verified_no_size_query)
            verified = await _scalar_one_or_none(verified_no_size_result)
        except Exception as exc:
            log.info("predict.verified_no_size_unavailable", error=str(exc))

        if _is_verified_product_match(verified):
            top = {
                "hsn_code": verified.hsn_code,
                "description": verified.description,
                "gst_rate": float(verified.gst_rate or 0) if verified.gst_rate else None,
                "score": 0.95,
                "method": "verified_no_size",
            }
            alternatives = []
            confidence, label = score_result(0.95)
            needs_review = False
            elapsed = (time.perf_counter() - start) * 1000
        else:
            # Pass 1+: upgraded DB-backed matching, then local matcher fallback
            matches = await match_query(body.text, db, top_k=5)
            if not matches:
                matcher = get_matcher()
                matches = matcher.match(body.text, top_k=5)
            if not matches:
                raise HTTPException(status_code=422, detail="No HSN matches found for this description")

            top = matches[0]
            alternatives = matches[1:]
            confidence, label = score_result(top["score"])
            needs_review = top["score"] < 0.55
            elapsed = (time.perf_counter() - start) * 1000

    try:
        record = Prediction(
            request_id=request_id,
            input_text=body.text,
            predicted_hsn=top["hsn_code"],
            confidence=confidence,
            needs_review=needs_review,
            api_key_hash=hashlib.sha256(api_key.encode()).hexdigest()[:16],
        )
        db.add(record)
        await db.commit()
    except Exception as exc:
        log.info("predict.persistence_unavailable", error=str(exc))
        try:
            await db.rollback()
        except Exception:
            pass

    # --- ADDED: GST ---
    # Primary GST fields: rate + dates from hsn_codes (nightly sync) or live fetcher
    gst_fields = await _build_gst_fields(top["hsn_code"], db)
    # Overlay effective_from / effective_to / gst_note from GSTRateHistory if available
    gst_dates = await get_gst_dates(top["hsn_code"], db)
    if gst_dates["gst_effective_from"] is not None:
        gst_fields["gst_effective_from"] = gst_dates["gst_effective_from"]
        gst_fields["gst_effective_to"] = gst_dates["gst_effective_to"]
        gst_fields["gst_note"] = gst_dates["gst_note"]
    # --- ADDED: GST ---

    result = PredictResponse(
        request_id=request_id,
        input_text=body.text,
        top_match=top,
        alternatives=alternatives,
        confidence=confidence,
        confidence_label=label,
        needs_review=needs_review,
        processing_time_ms=round(elapsed, 1),
        # --- ADDED: GST ---
        gst_rate=gst_fields["gst_rate"],
        gst_note=gst_fields["gst_note"],
        gst_effective_from=gst_fields["gst_effective_from"],
        gst_effective_to=gst_fields["gst_effective_to"],
        # --- ADDED: GST ---
    )
    await set_cache(cache_key, result.model_dump())
    return result


# --- ADDED: GST ---
@router.post(
    "/predict/bulk",
    summary="Bulk predict HSN codes and export as CSV",
    response_class=StreamingResponse,
)
async def predict_bulk(
    body: list[PredictRequest],
    request: Request,
    api_key: str = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept a JSON array of {"text": "..."} objects.
    Returns a CSV file with columns:
      Input Text, HSN Code, Description, Confidence, Method, GST %
    Max 200 items per request.
    """
    if len(body) > 200:
        raise HTTPException(status_code=422, detail="Maximum 200 items per bulk request")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Input Text", "HSN Code", "Description", "Confidence", "Method", "GST %"])

    for item in body:
        try:
            cache_key = f"predict:{item.text.strip().lower()}"
            cached = await get_cache(cache_key)

            if cached:
                top = cached.get("top_match", {})
                confidence = cached.get("confidence", 0.0)
                gst_rate = cached.get("gst_rate")
            else:
                # Verified exact match
                verified = None
                try:
                    vq = select(VerifiedProduct).where(
                        VerifiedProduct.description_normalized == item.text.upper().strip()
                    )
                    vr = await db.execute(vq)
                    verified = await _scalar_one_or_none(vr)
                except Exception:
                    pass

                if _is_verified_product_match(verified):
                    top = {
                        "hsn_code": verified.hsn_code,
                        "description": verified.description,
                        "score": 1.0,
                        "method": "verified_exact",
                    }
                    confidence, _ = score_result(1.0)
                else:
                    matches = await match_query(item.text, db, top_k=1)
                    if not matches:
                        matcher = get_matcher()
                        matches = matcher.match(item.text, top_k=1)
                    if not matches:
                        writer.writerow([item.text, "NOT FOUND", "", "", "", "N/A"])
                        continue
                    top = matches[0]
                    confidence, _ = score_result(top["score"])

                gst_fields = await _build_gst_fields(top["hsn_code"], db)
                gst_rate = gst_fields["gst_rate"]

            gst_str = f"{gst_rate:.2f}" if gst_rate is not None else "N/A"
            writer.writerow([
                item.text,
                top.get("hsn_code", ""),
                top.get("description", ""),
                f"{confidence:.4f}",
                top.get("method", ""),
                gst_str,
            ])
        except Exception as exc:
            log.warning("predict.bulk_item_error", text=item.text[:50], error=str(exc))
            writer.writerow([item.text, "ERROR", str(exc)[:80], "", "", "N/A"])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=hsn_predictions.csv"},
    )
# --- ADDED: GST ---
