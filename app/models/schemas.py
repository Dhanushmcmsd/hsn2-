from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime              # --- ADDED: GST ---


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
    # --- ADDED: GST ---
    gst_rate: Optional[float] = None
    gst_note: Optional[str] = None
    gst_effective_from: Optional[str] = None     # ISO date string YYYY-MM-DD
    gst_effective_to: Optional[str] = None       # null = currently active
    # --- ADDED: GST ---


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


# --- ADDED: GST ---
class GstChangeItem(BaseModel):
    """One row from gst_change_log, returned by GET /admin/gst/changes."""
    id: int
    hsn_code: str
    old_rate: Optional[float] = None
    new_rate: float
    changed_at: datetime
    source: str
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class GstChangesResponse(BaseModel):
    items: list[GstChangeItem]
    total: int
    page: int
    per_page: int
# --- ADDED: GST ---
