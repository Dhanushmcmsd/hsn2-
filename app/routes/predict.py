from __future__ import annotations
import asyncio
import hashlib
import inspect
import os
import re
import time
import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import async_session, get_db, Prediction, VerifiedProduct
from app.models.schemas import (
    BatchQuery,
    BatchResponse,
    HSNBatchResult,
    PredictRequest,
    PredictResponse,
)
from app.services import gst_classifier
from app.services.classify_adapter import (
    is_authoritative_classify,
    to_batch_result,
    to_predict_response,
)
from app.services.matcher import strip_sizes
from app.services.kerala_search import kerala_fallback_search
from app.services.retail_preprocess import (
    preprocess_retail_query,
    retail_alias_query,
    retail_kerala_query,
)
from app.services.search_thresholds import (
    PREDICT_BRAND_SIM_THRESHOLD,
    PREDICT_INVERTED_SIM_THRESHOLD,
    PREDICT_PRODUCT_SIM_THRESHOLD,
    PREDICT_TRGM_SIM_THRESHOLD,
)
from app.services.db_matcher import match_query
from app.services.confidence import score_result
from app.services.normalizer import normalize_product_name
from app.services.product_search import (
    search_by_product_name,
    search_by_brand_and_type,
    search_by_token_ilike,
    search_in_memory,
)
from app.services import inverted_index
from app.services.pg_search import search as pg_search
from app.services.brand_search import brand_lookup, is_unclassified_hsn
from app.utils.auth import require_api_key
from app.utils.cache import get_cache, set_cache
from app.utils.rate_limit import check_rate_limit

router = APIRouter(tags=["predict"])
log = structlog.get_logger()

BULK_CONCURRENCY = int(os.environ.get("BULK_CONCURRENCY", "12"))
BULK_PER_QUERY_TIMEOUT_S = float(os.environ.get("BULK_PER_QUERY_TIMEOUT_S", "15"))
BULK_RESULT_CACHE_TTL_S = int(os.environ.get("BULK_RESULT_CACHE_TTL_S", "21600"))
BULK_MAX_QUERIES_PER_REQUEST = int(os.environ.get("BULK_MAX_QUERIES_PER_REQUEST", "50"))

# ── Unified cache key format (same as main.py) ─────────────────────────────────────────────────────
_QUERY_NORMALIZE_RE = re.compile(r"\s+")

def _normalize_confidence(score: float, source: str) -> int:
    """
    Normalizes raw layer scores to a consistent 0–100 integer for UI display.
    """
    ranges = {
        "exact":              (1.0, 1.0),
        "verified_exact":     (0.92, 1.0),
        "inverted_index":     (0.0, 1.0),
        "trigram":            (0.0, 1.0),
        "faiss":              (0.0, 1.0),
        "synonym_fuzzy":      (0.0, 1.0),
        "product_trigram":    (0.0, 1.0),
        "product_ilike":      (0.0, 1.0),
        "product_rapidfuzz":  (0.0, 1.0),
        "product_brand_type": (0.0, 1.0),
        "pg_exact":             (0.0, 1.0),
        "pg_trgm_verified":     (0.0, 1.0),
        "pg_fts_hsn":           (0.0, 1.0),
        "pg_trgm_hsn":          (0.0, 1.0),
    }
    low, high = ranges.get(source, (0.0, 1.0))
    if high == low:
        return 100
    normalized = (score - low) / (high - low)
    return min(100, max(0, round(normalized * 100)))


def _normalize_query_for_cache(q: str) -> str:
    """Normalize query for cache key generation - matches main.py format."""
    return _QUERY_NORMALIZE_RE.sub(" ", (q or "").strip()).upper()


def _match_cache_key(query: str) -> str:
    """
    Unified cache key format for HSN matching results.
    Format: match:v1:<sha1 of normalized query>
    Matches main.py /predict and /hsn/batch endpoints.
    """
    norm = _normalize_query_for_cache(query)
    return "match:v1:" + hashlib.sha1(norm.encode("utf-8")).hexdigest()


def _predict_from_cached(
    cached: dict,
    *,
    request_id: str,
    input_text: str,
) -> PredictResponse | None:
    """Accept PredictResponse cache entries or bulk row_dict payloads."""
    if not isinstance(cached, dict):
        return None
    if cached.get("top_match") and cached.get("request_id"):
        try:
            return PredictResponse(**cached)
        except Exception:
            pass
    if cached.get("hsn_code"):
        conf = float(cached.get("confidence") or 0)
        if conf > 1:
            conf = conf / 100.0
        return to_predict_response(
            request_id,
            input_text,
            {
                "hsn_code": cached.get("hsn_code"),
                "description": cached.get("description") or "",
                "gst_rate": cached.get("gst_rate"),
                "confidence": int(conf * 100) if conf <= 1 else int(conf),
                "matched_layer": cached.get("match_method") or cached.get("source"),
                "review_required": bool(cached.get("error")),
                "alternates": cached.get("alternatives") or [],
            },
            processing_time_ms=0.0,
        )
    return None


async def _scalar_one_or_none(result):
    value = result.scalar_one_or_none()
    if inspect.isawaitable(value):
        value = await value
    return value


def _is_verified_product_match(candidate) -> bool:
    return isinstance(getattr(candidate, "hsn_code", None), str) and isinstance(
        getattr(candidate, "description", None), str
    )


async def _fetch_verified_single_pass(db: AsyncSession, body_text: str):
    """One round-trip for exact / Kerala-expanded / no-size verified rows (priority preserved)."""
    normalized = body_text.upper().strip()
    no_size_val = strip_sizes(body_text)
    prep = preprocess_retail_query(body_text, for_classify=False)
    kerala_norm = (prep.malayalam_expanded or body_text).upper().strip()

    priority = case(
        (VerifiedProduct.description_normalized == normalized, 1),
        (VerifiedProduct.description_normalized == kerala_norm, 2),
        (VerifiedProduct.description_no_size == no_size_val, 3),
        else_=4,
    )
    stmt = (
        select(VerifiedProduct)
        .where(
            or_(
                VerifiedProduct.description_normalized == normalized,
                VerifiedProduct.description_normalized == kerala_norm,
                VerifiedProduct.description_no_size == no_size_val,
            )
        )
        .order_by(priority)
        .limit(1)
    )
    try:
        verified_result = await db.execute(stmt)
        return await _scalar_one_or_none(verified_result), normalized, kerala_norm, no_size_val
    except Exception as exc:
        log.info("predict.verified_combined_unavailable", error=str(exc))
        return None, normalized, kerala_norm, no_size_val


def _verified_score_method(verified, normalized: str, kerala_norm: str, no_size_val: str) -> tuple[float, str]:
    if verified.description_normalized == normalized:
        return 1.0, "verified_exact"
    if verified.description_normalized == kerala_norm:
        return 0.92, "verified_kerala_expanded"
    if verified.description_no_size == no_size_val:
        return 0.95, "verified_no_size"
    return 1.0, "verified_exact"


@router.post("/predict", response_model=PredictResponse)
async def predict(
    body: PredictRequest,
    request: Request,
    api_key: str = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    await check_rate_limit(api_key)

    request_id = str(uuid.uuid4())

    prep = preprocess_retail_query(body.text or "", for_classify=False)
    normalized_query = prep.normalized or normalize_product_name(body.text)
    if not normalized_query:
        normalized_query = (body.text or "").strip()
    if not normalized_query:
        raise HTTPException(status_code=422, detail="Product description is empty")

    # Same cache key as /hsn/batch (raw invoice text) so single and bulk stay in sync.
    cache_key = _match_cache_key(body.text.strip())
    cached = await get_cache(cache_key)
    if cached:
        hit = _predict_from_cached(cached, request_id=request_id, input_text=body.text)
        if hit:
            log.info("predict.cache_hit", text=body.text[:50])
            return hit

    start = time.perf_counter()

    # ── Unified 6-tier classifier (same pipeline as /api/v1/classify & bulk) ───
    try:
        classify_out = await gst_classifier.classify(db, body.text, bypass_cache=False)
        if is_authoritative_classify(classify_out):
            elapsed = (time.perf_counter() - start) * 1000
            response = to_predict_response(
                request_id,
                body.text,
                classify_out,
                processing_time_ms=elapsed,
            )
            await set_cache(cache_key, response.model_dump(), ttl=BULK_RESULT_CACHE_TTL_S)
            try:
                record = Prediction(
                    request_id=request_id,
                    input_text=body.text,
                    predicted_hsn=response.top_match.hsn_code,
                    confidence=int(response.confidence * 100),
                    needs_review=response.needs_review,
                    api_key_hash=hashlib.sha256(api_key.encode()).hexdigest()[:16],
                    source=response.top_match.method,
                )
                db.add(record)
                await db.commit()
            except Exception as exc:
                log.warning("predict.classify_persist_failed", error=str(exc)[:80])
                try:
                    await db.rollback()
                except Exception:
                    pass
            log.info(
                "predict.classify_hit",
                query=body.text[:60],
                hsn=response.top_match.hsn_code,
                layer=classify_out.get("matched_layer"),
            )
            return response
    except Exception as exc:
        log.warning("predict.classify_failed", error=str(exc)[:120])

    search_text = normalized_query
    try:
        from app.services import aliases as alias_svc

        alias_input = retail_alias_query(prep, fallback=normalized_query)
        expanded = await alias_svc.expand_query(db, alias_input, for_classify=False)
        if expanded.english_query and expanded.english_query.strip():
            search_text = expanded.english_query.strip()
    except Exception as exc:
        log.info("predict.alias_expand_skipped", error=str(exc))

    # ── Tier-0: Brand alias / brand-column lookup (fastest, most precise) ────
    # Runs BEFORE the verified_products exact match to catch brand-name-only
    # queries like "BOOST", "HORLICKS", "COLGATE" that would otherwise fall
    # through to low-confidence FAISS / synonym rescue paths.
    # NOTE: brand_lookup now guards against generic commodity words (milk,
    # broom, toothbrush, etc.) and returns None for them immediately.
    brand_result: dict | None = None
    try:
        brand_result = await brand_lookup(
            db,
            search_text,
            min_score=PREDICT_BRAND_SIM_THRESHOLD,
            for_classify=False,
        )
    except Exception as exc:
        log.info("predict.brand_lookup_failed", error=str(exc))

    if brand_result and not is_unclassified_hsn(brand_result.get("hsn_code")):
        top = brand_result
        alternatives = []
        confidence, label = score_result(top["score"])
        needs_review = False
        prediction_source = top.get("method", "brand_lookup")
        elapsed = (time.perf_counter() - start) * 1000
        result = top

        # Persist and cache so subsequent identical queries are instant
        norm_conf = _normalize_confidence(top["score"], prediction_source)
        cache_payload = {
            "hsn_code":    top["hsn_code"],
            "description": top["description"],
            "gst_rate":    top["gst_rate"],
            "source":      prediction_source,
            "confidence":  norm_conf,
        }
        await set_cache(cache_key, cache_payload, ttl=86400)
        log.info("predict.brand_hit", query=body.text[:60], hsn=top["hsn_code"], method=prediction_source)

        record = Prediction(
            request_id=request_id,
            input_text=body.text,
            predicted_hsn=top["hsn_code"],
            confidence=norm_conf,
            needs_review=False,
            api_key_hash=hashlib.sha256(api_key.encode()).hexdigest()[:16],
            source=prediction_source,
        )
        try:
            db.add(record)
            await db.commit()
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass

        return PredictResponse(
            request_id=request_id,
            input_text=body.text,
            top_match=top,
            alternatives=[],
            confidence=norm_conf,
            confidence_label=label,
            needs_review=False,
            processing_time_ms=round(elapsed, 1),
        )

    verified = None
    try:
        verified, normalized, kerala_norm, no_size_val = await _fetch_verified_single_pass(db, search_text)
    except Exception as exc:
        log.info("predict.verified_fetch_failed", error=str(exc))
        verified, normalized, kerala_norm, no_size_val = None, search_text.upper().strip(), "", ""

    prediction_source: str | None = None

    if _is_verified_product_match(verified):
        score, method = _verified_score_method(verified, normalized, kerala_norm, no_size_val)
        top = {
            "hsn_code": verified.hsn_code,
            "description": verified.description,
            "gst_rate": float(verified.gst_rate or 0) if verified.gst_rate else None,
            "score": score,
            "method": method,
            "source": method,
        }
        alternatives = []
        confidence, label = score_result(score)
        needs_review = False
        prediction_source = method
        elapsed = (time.perf_counter() - start) * 1000
    else:
        inv_matches = await inverted_index.search(db, search_text, limit=5)
        if inv_matches and inv_matches[0].get("score", 0) >= PREDICT_INVERTED_SIM_THRESHOLD:
            top = inv_matches[0]
            top.setdefault("source", "inverted_index")
            alternatives = inv_matches[1:]
            confidence, label = score_result(top["score"])
            needs_review = top["score"] < 0.55
            prediction_source = "inverted_index"
            elapsed = (time.perf_counter() - start) * 1000
        else:
            trgm_matches = await inverted_index.fuzzy_trgm(db, search_text, limit=5)
            if trgm_matches and trgm_matches[0].get("score", 0) >= PREDICT_TRGM_SIM_THRESHOLD:
                top = trgm_matches[0]
                top.setdefault("source", "trigram")
                alternatives = trgm_matches[1:]
                confidence, label = score_result(top["score"])
                needs_review = top["score"] < 0.55
                prediction_source = "trigram"
                elapsed = (time.perf_counter() - start) * 1000
            else:
                matches: list[dict] = []
                prod_result = await search_by_product_name(db, search_text)
                if not prod_result:
                    prod_result = await search_by_brand_and_type(db, search_text)
                if prod_result and prod_result.get("score", 0) >= PREDICT_PRODUCT_SIM_THRESHOLD:
                    matches = [prod_result]
                else:
                    pg_results = await pg_search(db, search_text, top_k=5)
                    if pg_results and pg_results[0].get("score", 0) >= 0.25:
                        matches = pg_results
                    else:
                        kerala_results = await kerala_fallback_search(
                            retail_kerala_query(prep, fallback=search_text),
                            db,
                            top_k=5,
                        )
                        if kerala_results:
                            matches = kerala_results
                        else:
                            # ── FIXED: Always call match_query as final fallback;
                            # do NOT raise 422 here. match_query covers FAISS,
                            # synonym expansion, and the broad HSN chapter table.
                            # Only raise 422 when match_query also returns nothing.
                            matches = await match_query(search_text, db, top_k=5) or []

                if not matches:
                    raise HTTPException(status_code=422, detail="No HSN matches found for this description")

                top = matches[0]
                alternatives = matches[1:]
                if not top.get("source"):
                    top["source"] = top.get("method") or "hsn_codes"
                confidence, label = score_result(top["score"])
                needs_review = top["score"] < 0.55
                prediction_source = top.get("method") or top.get("source") or "unknown"
                elapsed = (time.perf_counter() - start) * 1000

    result = top

    # ── Error boundary: reject 99999999 for known brands ──────────────────────
    # If all search tiers returned 99999999 / unclassified but we have a brand
    # alias hit, use the alias result rather than returning the catch-all code.
    if is_unclassified_hsn(result.get("hsn_code")) and brand_result:
        result = brand_result
        top = brand_result
        alternatives = []
        confidence, label = score_result(brand_result["score"])
        needs_review = True
        prediction_source = brand_result.get("method", "brand_lookup_fallback")
        elapsed = (time.perf_counter() - start) * 1000
        log.warning(
            "predict.unclassified_rescued_by_brand",
            query=body.text[:60],
            hsn=brand_result["hsn_code"],
        )

    # ── Product Name Search Layer (token ILIKE + in-memory; tier 3.5 covers trigram) ──
    if not result or result.get("score", 0) < 0.30:
        product_result = await search_by_token_ilike(db, body.text)
        if not product_result:
            product_result = search_in_memory(body.text, getattr(request.app.state, "product_name_cache", []))

        if product_result:
            result = product_result
            top = product_result
            alternatives = []
            confidence, label = score_result(result["score"])
            needs_review = result["score"] < 0.55
            prediction_source = result["source"]
            elapsed = (time.perf_counter() - start) * 1000

            norm_conf = _normalize_confidence(result["score"], result["source"])
            cache_payload = {
                "hsn_code":    result["hsn_code"],
                "description": result["description"],
                "gst_rate":    result["gst_rate"],
                "source":      result["source"],
                "confidence":  norm_conf
            }
            await set_cache(
                key=cache_key,
                value=cache_payload,
                ttl=86400
            )

            from sqlalchemy import text
            try:
                await db.execute(text("""
                    INSERT INTO predictions (request_id, input_text, predicted_hsn, confidence, source, created_at)
                    VALUES (:req, :input, :hsn, :conf, :src, NOW())
                    ON CONFLICT DO NOTHING
                """), {
                    "req": request_id,
                    "input": body.text,
                    "hsn":   result["hsn_code"],
                    "conf":  norm_conf,
                    "src":   result["source"]
                })
                await db.commit()
            except Exception as exc:
                log.warning("predict.product_insert_failed", error=str(exc))
                try:
                    await db.rollback()
                except Exception:
                    pass

    # Normalize confidence across all layers
    result_source = prediction_source or result.get("source") or result.get("method") or "unknown"
    result["source"] = result_source
    confidence = _normalize_confidence(result["score"], result_source)
    label = score_result(result["score"])[1]
    prediction_source = result_source

    try:
        record = Prediction(
            request_id=request_id,
            input_text=body.text,
            predicted_hsn=top["hsn_code"],
            confidence=confidence,
            needs_review=needs_review,
            api_key_hash=hashlib.sha256(api_key.encode()).hexdigest()[:16],
            source=prediction_source,
        )
        db.add(record)
        await db.commit()
    except Exception as exc:
        log.warning("predict.persistence_unavailable", error=str(exc))
        try:
            await db.rollback()
        except Exception:
            pass

    result = PredictResponse(
        request_id=request_id,
        input_text=body.text,
        top_match=top,
        alternatives=alternatives,
        confidence=confidence,
        confidence_label=label,
        needs_review=needs_review,
        processing_time_ms=round(elapsed, 1),
    )
    await set_cache(cache_key, result.model_dump(), ttl=None)
    return result


def _bulk_normalize_query(q: str) -> str:
    return _QUERY_NORMALIZE_RE.sub(" ", (q or "").strip()).upper()


@router.post("/hsn/batch", response_model=BatchResponse)
async def batch_predict(
    body: BatchQuery,
    api_key: str = Depends(require_api_key),
) -> BatchResponse:
    """Bulk classify product descriptions (same gst_classifier pipeline as /predict)."""
    await check_rate_limit(api_key)

    raw_queries = [q.strip() for q in body.queries if q and q.strip()]
    if not raw_queries:
        return BatchResponse(results=[], total=0, matched=0, unmatched=0)
    if len(raw_queries) > BULK_MAX_QUERIES_PER_REQUEST:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Maximum {BULK_MAX_QUERIES_PER_REQUEST} products per batch request. "
                "The app sends smaller chunks automatically after redeploy."
            ),
        )

    prev_faiss = os.environ.get("FAISS_DISABLED")
    os.environ["FAISS_DISABLED"] = "1"
    try:
        return await _batch_predict_inner(raw_queries)
    finally:
        if prev_faiss is None:
            os.environ.pop("FAISS_DISABLED", None)
        else:
            os.environ["FAISS_DISABLED"] = prev_faiss


async def _batch_predict_inner(raw_queries: list[str]) -> BatchResponse:
    groups: dict[str, list[int]] = {}
    keys_in_order: list[str] = []
    for idx, query in enumerate(raw_queries):
        norm = _bulk_normalize_query(query)
        if norm not in groups:
            groups[norm] = []
            keys_in_order.append(norm)
        groups[norm].append(idx)

    unique_queries = [(norm, raw_queries[groups[norm][0]]) for norm in keys_in_order]
    cache_keys = [_match_cache_key(orig) for _norm, orig in unique_queries]
    cached_payloads = await asyncio.gather(
        *(get_cache(k) for k in cache_keys),
        return_exceptions=True,
    )

    by_norm: dict[str, HSNBatchResult] = {}
    misses: list[tuple[str, str, str]] = []

    for (_norm, orig), payload, cache_key in zip(unique_queries, cached_payloads, cache_keys):
        row_dict: dict | None = None
        if isinstance(payload, dict):
            if payload.get("hsn_code"):
                row_dict = to_batch_result(orig, payload)
            elif payload.get("top_match"):
                tm = payload["top_match"] or {}
                conf = float(payload.get("confidence") or tm.get("score") or 0)
                row_dict = to_batch_result(orig, {
                    "hsn_code": tm.get("hsn_code"),
                    "description": tm.get("description"),
                    "gst_rate": tm.get("gst_rate"),
                    "confidence": int(conf * 100) if conf <= 1 else int(conf),
                    "matched_layer": tm.get("method"),
                    "alternates": payload.get("alternatives") or [],
                })
        if row_dict and row_dict.get("hsn_code"):
            by_norm[_norm] = HSNBatchResult(**row_dict)
        else:
            misses.append((_norm, orig, cache_key))

    if misses:
        sem = asyncio.Semaphore(max(1, BULK_CONCURRENCY))

        async def _resolve(orig_query: str, cache_key: str) -> HSNBatchResult:
            async with sem:
                try:
                    async with async_session() as session:
                        classify_out = await asyncio.wait_for(
                            gst_classifier.classify(session, orig_query, bypass_cache=False),
                            timeout=BULK_PER_QUERY_TIMEOUT_S,
                        )
                except asyncio.TimeoutError:
                    log.warning("batch.timeout", query=orig_query[:60])
                    return HSNBatchResult(
                        query=orig_query,
                        error="Classification timed out for this item.",
                    )
                except Exception as exc:
                    log.error("batch.classify_failed", query=orig_query[:60], error=str(exc)[:80])
                    return HSNBatchResult(
                        query=orig_query,
                        error="Classification failed. Please try again or contact support.",
                    )

                row_dict = to_batch_result(orig_query, classify_out)
                result = HSNBatchResult(**row_dict)
                if result.hsn_code:
                    try:
                        await set_cache(cache_key, row_dict, ttl=BULK_RESULT_CACHE_TTL_S)
                    except Exception:
                        pass
                return result

        resolved = await asyncio.gather(
            *(_resolve(orig, key) for _norm, orig, key in misses),
            return_exceptions=False,
        )
        for (_norm, orig, _key), row in zip(misses, resolved):
            by_norm[_norm] = row

    results: list[HSNBatchResult] = [HSNBatchResult(query="")] * len(raw_queries)
    for norm, positions in groups.items():
        base = by_norm.get(norm) or HSNBatchResult(
            query=raw_queries[positions[0]],
            error="Classification failed. Please try again or contact support.",
        )
        base_dump = base.model_dump()
        for pos in positions:
            cloned = dict(base_dump)
            cloned["query"] = raw_queries[pos]
            results[pos] = HSNBatchResult(**cloned)

    matched = sum(1 for r in results if r.hsn_code)
    return BatchResponse(
        results=results,
        total=len(results),
        matched=matched,
        unmatched=len(results) - matched,
    )
