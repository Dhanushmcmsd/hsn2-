from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional


class PredictRequest(BaseModel):
    text: str = Field(..., min_length=2, max_length=500, description="Product description")


class HSNMatch(BaseModel):
    hsn_code: str
    description: str
    full_description: Optional[str] = None
    score: float
    method: str = "semantic"
    gst_rate: Optional[float] = None
    chapter: Optional[str] = None
    heading: Optional[str] = None


class PredictResponse(BaseModel):
    request_id: str
    input_text: str
    top_match: HSNMatch
    alternatives: list[HSNMatch]
    confidence: float
    confidence_label: str
    needs_review: bool
    processing_time_ms: float


class BatchQuery(BaseModel):
    queries: list[str] = Field(..., min_length=1, max_length=1000)


class HSNBatchResult(BaseModel):
    query: str
    hsn_code: Optional[str] = None
    description: Optional[str] = None
    gst_rate: Optional[float] = None
    confidence: float = 0.0
    confidence_label: str = "low"
    match_method: str = "none"
    alternatives: list[dict] = Field(default_factory=list)
    error: Optional[str] = None


class BatchResponse(BaseModel):
    results: list[HSNBatchResult]
    total: int
    matched: int
    unmatched: int


class HSNRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hsn_code: str
    description: str
    full_description: str
    gst_rate: float
    category: Optional[str] = None
    chapter: Optional[str] = None
    heading: Optional[str] = None
    section: Optional[str] = None


class ResolveRequest(BaseModel):
    request_id: str
    corrected_hsn: str


class ReviewItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: str
    input_text: str
    predicted_hsn: str
    confidence: float


class ImportantProduct(BaseModel):
    product_name: str
    hsn_code: str = ""
    source_name: str = ""
    cleaned_description: str = ""
    pack_or_size: str = ""
    status: str = "pending"
    confidence: float = 0.0


class ProductAnalysisRequest(BaseModel):
    product_index: int
    force_update: bool = False


class ProductAnalysisResponse(BaseModel):
    product_index: int
    original_name: str
    cleaned_description: str
    hsn_analysis: dict
    auto_updated: bool
    message: str


# ── Pending products (/pending/*) ─────────────────────────────────────────────


class PendingProductItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_name: str
    source_name: Optional[str] = None
    pack_or_size: Optional[str] = None
    hsn_code: Optional[str] = None
    status: str


class PendingProductsResponse(BaseModel):
    items: list[PendingProductItem]
    total: int


class PendingProductResolve(BaseModel):
    hsn_code: str = Field(..., min_length=4, max_length=20, description="Confirmed HSN code")
    status: str = Field("resolved", description="New status: resolved, rejected, pending")


# ── Product search layer (/search/*) ─────────────────────────────────────────


class SearchFilters(BaseModel):
    min_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    categories: Optional[list[str]] = None
    gst_rate: Optional[float] = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Free-text product description or HSN prefix")
    top_k: int = Field(10, ge=1, le=50)
    filters: Optional[SearchFilters] = None


class SearchResult(BaseModel):
    hsn_code: str
    description: str
    score: float
    match_type: str
    gst_rate: Optional[float] = None
    category: Optional[str] = None
    highlighted: Optional[str] = None


class SearchMetadata(BaseModel):
    total_candidates: int
    search_time_ms: float
    cache_hit: bool
    methods_used: list[str]


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    search_metadata: SearchMetadata


class PartialCodeMatch(BaseModel):
    code: str
    description: str
    gst_rate: Optional[float] = None
    category: Optional[str] = None


class PartialCodeSearchResponse(BaseModel):
    prefix: str
    matches: list[PartialCodeMatch]


class SearchSuggestionsResponse(BaseModel):
    q: str
    suggestions: list[str]


# ── Multi-layer search (/search/multi) ───────────────────────────────────────


class MultiSearchFilters(BaseModel):
    min_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    categories: Optional[list[str]] = None
    gst_rate: Optional[float] = None
    chapter: Optional[str] = None


class MultiSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(10, ge=1, le=50)
    filters: Optional[MultiSearchFilters] = None
    bypass_cache: bool = False
    explain: bool = False


class MultiSearchHit(BaseModel):
    hsn_code: str
    description: str
    score: float
    method: str
    gst_rate: Optional[float] = None
    category: Optional[str] = None
    chapter: Optional[str] = None
    brand: Optional[str] = None


class MultiSearchLayerTrace(BaseModel):
    name: str
    ms: float
    candidate_count: int
    used: bool = True
    error: Optional[str] = None


class MultiSearchAliasHint(BaseModel):
    hsn_code: str
    source_term: str
    language: str
    weight: float


class MultiSearchResponse(BaseModel):
    query: str
    detected_language: str
    english_query: str
    expansions: list[str]
    results: list[MultiSearchHit]
    cache_hit: bool
    total_time_ms: float
    methods_used: list[str]
    layers: list[MultiSearchLayerTrace] = []
    direct_hsn_hints: list[MultiSearchAliasHint] = []


class CategoryItem(BaseModel):
    category_code: str
    category_name: str
    section_code: str
    chapter_range_start: int
    chapter_range_end: int
    display_order: int
    official_source: Optional[str] = None
    description: Optional[str] = None
    code_count: int = 0


class CategoriesResponse(BaseModel):
    categories: list[CategoryItem]


class LanguageHit(BaseModel):
    hsn_code: str
    description: str
    gst_rate: Optional[float] = None
    category: Optional[str] = None
    chapter: Optional[str] = None
    matched_term: str
    english_term: Optional[str] = None
    weight: float


class LanguageSearchResponse(BaseModel):
    q: str
    language: str
    results: list[LanguageHit]
