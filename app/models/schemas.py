from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, validator


# ---------------------------------------------------------------------------
# Prediction schemas
# ---------------------------------------------------------------------------

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
    alternatives: List[HSNMatch]
    confidence: float
    confidence_label: str
    needs_review: bool
    processing_time_ms: float

    # --- GST fields ---
    gst_rate: Optional[float] = None
    gst_note: Optional[str] = None
    gst_effective_from: Optional[date] = None
    gst_effective_to: Optional[date] = None
    # --- GST fields ---

    @validator("gst_note", always=True, pre=False)
    def build_gst_note(cls, v, values):
        """Auto-build gst_note from gst_rate + gst_effective_from if not explicitly set."""
        if v is not None:
            return v  # caller provided an explicit value — respect it
        rate = values.get("gst_rate")
        eff_from = values.get("gst_effective_from")
        if rate is not None and eff_from is not None:
            return f"GST {rate:.0f}% \u2014 effective {eff_from.strftime('%d-%b-%Y')}"
        if rate is not None:
            return f"GST {rate:.0f}%"
        return None


# ---------------------------------------------------------------------------
# HSN lookup schema
# ---------------------------------------------------------------------------

class HSNRow(BaseModel):
    hsn_code: str
    description: str
    full_description: str
    gst_rate: float
    category: Optional[str] = None
    chapter: Optional[str] = None
    heading: Optional[str] = None
    section: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Review / resolution schemas
# ---------------------------------------------------------------------------

class ResolveRequest(BaseModel):
    request_id: str
    corrected_hsn: str


class ReviewItem(BaseModel):
    request_id: str
    input_text: str
    predicted_hsn: str
    confidence: float

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Admin — important products schemas
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# GST change-log schemas
# ---------------------------------------------------------------------------

class GSTChangeRecord(BaseModel):
    """One row from gst_change_log."""
    id: int
    hsn_code: str
    old_rate: Optional[float] = None
    new_rate: Optional[float] = None
    changed_at: datetime
    source: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        orm_mode = True          # Pydantic v1 compat
        from_attributes = True   # Pydantic v2 compat


# Alias kept for backwards compat with existing admin routes
GstChangeItem = GSTChangeRecord


class PaginatedGSTChanges(BaseModel):
    """Paginated wrapper for gst_change_log rows."""
    items: List[GSTChangeRecord]
    total: int
    page: int
    per_page: int


# Alias kept for backwards compat with existing admin routes
GstChangesResponse = PaginatedGSTChanges


# ---------------------------------------------------------------------------
# GST sync result schema
# ---------------------------------------------------------------------------

class GSTSyncResult(BaseModel):
    """Returned by POST /admin/gst/sync and trigger_gst_sync_now()."""
    status: str
    updated: int
    unchanged: int
    source: str
    duration_ms: int
