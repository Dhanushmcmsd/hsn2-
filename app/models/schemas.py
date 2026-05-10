from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    @field_validator("gst_note", mode="after")
    @classmethod
    def build_gst_note(cls, v, info):
        """Auto-build gst_note from gst_rate + gst_effective_from if not explicitly set."""
        if v is not None:
            return v
        data = info.data
        rate = data.get("gst_rate")
        eff_from = data.get("gst_effective_from")
        if rate is not None and eff_from is not None:
            return f"GST {rate:.0f}% \u2014 effective {eff_from.strftime('%d-%b-%Y')}"
        if rate is not None:
            return f"GST {rate:.0f}%"
        return None


# ---------------------------------------------------------------------------
# HSN lookup schema
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Review / resolution schemas
# ---------------------------------------------------------------------------

class ResolveRequest(BaseModel):
    request_id: str
    corrected_hsn: str


class ReviewItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: str
    input_text: str
    predicted_hsn: str
    confidence: float


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
    model_config = ConfigDict(from_attributes=True)

    id: int
    hsn_code: str
    old_rate: Optional[float] = None
    new_rate: Optional[float] = None
    changed_at: datetime
    source: Optional[str] = None
    notes: Optional[str] = None


# Alias kept for backwards compat with existing admin routes
GstChangeItem = GSTChangeRecord


class PaginatedGSTChanges(BaseModel):
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
    status: str
    updated: int
    unchanged: int
    source: str
    duration_ms: int
