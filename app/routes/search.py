"""Isolated product search API — prefix ``/search`` only; does not alter /predict or other routers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.schemas import (
    CategoriesResponse,
    CategoryItem,
    LanguageHit,
    LanguageSearchResponse,
    MultiSearchAliasHint,
    MultiSearchHit,
    MultiSearchLayerTrace,
    MultiSearchRequest,
    MultiSearchResponse,
    PartialCodeMatch,
    PartialCodeSearchResponse,
    SearchRequest,
    SearchResponse,
    SearchSuggestionsResponse,
)
from app.services import multi_layer_search, search_service
from app.utils.auth import require_api_key

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/products", response_model=SearchResponse)
async def search_products(
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(require_api_key),
) -> SearchResponse:
    return await search_service.search_products(
        db, body.query, top_k=body.top_k, filters=body.filters
    )


@router.get("/code/{prefix}", response_model=PartialCodeSearchResponse)
async def search_by_code_prefix(
    prefix: str,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(require_api_key),
    limit: int = Query(50, ge=1, le=200),
) -> PartialCodeSearchResponse:
    rows = await search_service.partial_code_prefix_search(db, prefix, limit=limit)
    return PartialCodeSearchResponse(
        prefix=prefix.strip(),
        matches=[
            PartialCodeMatch(
                code=r["code"],
                description=r["description"],
                gst_rate=r.get("gst_rate"),
                category=r.get("category"),
            )
            for r in rows
        ],
    )


@router.get("/suggestions", response_model=SearchSuggestionsResponse)
async def search_suggestions(
    q: str = Query("", min_length=1, max_length=200),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(require_api_key),
    limit: int = Query(8, ge=1, le=30),
) -> SearchSuggestionsResponse:
    suggestions = await search_service.search_suggestions(db, q, limit=limit)
    return SearchSuggestionsResponse(q=q.strip(), suggestions=suggestions)


# ── Multi-layer pipeline ─────────────────────────────────────────────────────


def _trace(t) -> MultiSearchLayerTrace:
    return MultiSearchLayerTrace(name=t.name, ms=round(t.ms, 2), candidate_count=t.candidate_count, used=t.used, error=t.error)


def _hit(row: dict) -> MultiSearchHit:
    return MultiSearchHit(
        hsn_code=str(row.get("hsn_code") or ""),
        description=str(row.get("description") or ""),
        score=float(row.get("score") or 0.0),
        method=str(row.get("method") or ""),
        gst_rate=float(row["gst_rate"]) if row.get("gst_rate") is not None else None,
        category=row.get("category"),
        chapter=str(row["chapter"]) if row.get("chapter") is not None else None,
        brand=row.get("brand"),
    )


@router.post("/multi", response_model=MultiSearchResponse)
async def multi_search(
    body: MultiSearchRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(require_api_key),
) -> MultiSearchResponse:
    """Multi-layer search: alias \u2192 cache \u2192 inverted-index \u2192 fuzzy \u2192 FAISS \u2192 verified \u2192 prefix."""
    filters = body.filters.model_dump(exclude_none=True) if body.filters else None
    out = await multi_layer_search.multi_search(
        db,
        body.query,
        top_k=body.top_k,
        filters=filters,
        bypass_cache=body.bypass_cache,
        explain=body.explain,
    )
    return MultiSearchResponse(
        query=out.query,
        detected_language=out.detected_language,
        english_query=out.english_query,
        expansions=out.expansions,
        results=[_hit(r) for r in out.results],
        cache_hit=out.cache_hit,
        total_time_ms=round(out.total_time_ms, 2),
        methods_used=out.methods_used,
        layers=[_trace(t) for t in out.layers],
        direct_hsn_hints=[MultiSearchAliasHint(**h) for h in out.direct_hsn_hints],
    )


@router.get("/explain", response_model=MultiSearchResponse)
async def multi_search_explain(
    q: str = Query(..., min_length=1, max_length=500),
    top_k: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(require_api_key),
) -> MultiSearchResponse:
    """Diagnostic: same as /multi but always returns full layer trace and bypasses cache."""
    out = await multi_layer_search.multi_search(
        db, q, top_k=top_k, filters=None, bypass_cache=True, explain=True
    )
    return MultiSearchResponse(
        query=out.query,
        detected_language=out.detected_language,
        english_query=out.english_query,
        expansions=out.expansions,
        results=[_hit(r) for r in out.results],
        cache_hit=False,
        total_time_ms=round(out.total_time_ms, 2),
        methods_used=out.methods_used,
        layers=[_trace(t) for t in out.layers],
        direct_hsn_hints=[MultiSearchAliasHint(**h) for h in out.direct_hsn_hints],
    )


@router.get("/categories", response_model=CategoriesResponse)
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(require_api_key),
) -> CategoriesResponse:
    """List the 11 official Indian Customs Tariff product categories."""
    rows = await multi_layer_search.list_categories(db)
    return CategoriesResponse(categories=[CategoryItem(**r) for r in rows])


@router.get("/by-language", response_model=LanguageSearchResponse)
async def search_by_language(
    q: str = Query(..., min_length=1, max_length=200),
    lang: str = Query(..., pattern="^(hi|ml|en)$"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(require_api_key),
) -> LanguageSearchResponse:
    """Direct lookup against the curated Hindi / Malayalam / English alias table."""
    if lang not in {"hi", "ml", "en"}:
        raise HTTPException(status_code=400, detail="lang must be one of hi, ml, en")
    rows = await multi_layer_search.search_by_language(db, q, lang, limit=limit)
    return LanguageSearchResponse(q=q.strip(), language=lang, results=[LanguageHit(**r) for r in rows])
