from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Prediction schemas
# ---------------------------------------------------------------------------

class PredictRequest(BaseModel):
    text: str = Field(..., min_length=2, max_length=500, description="Product description")

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        v = value.strip()
        if re.search(r"[\x00-\x1f\x7f]", v):
            raise ValueError("Control characters are not allowed")
        if len(v) > 2000:
            raise ValueError("Maximum 2000 characters allowed")
        return v


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

    @field_validator("corrected_hsn")
    @classmethod
    def validate_hsn(cls, value: str) -> str:
        v = value.strip()
        if not re.match(r"^[0-9]{2,8}$", v):
            raise ValueError("HSN code must match ^[0-9]{2,8}$")
        return v


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


class OrganisationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    gstin_prefix: Optional[str] = Field(default=None, max_length=15)


class OrganisationRead(BaseModel):
    id: UUID
    name: str
    gstin_prefix: Optional[str] = None
    is_active: bool
    created_at: datetime
    branch_count: Optional[int] = None


class BranchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    city: Optional[str] = Field(default=None, max_length=100)
    state_code: Optional[str] = Field(default=None, min_length=2, max_length=2)
    gstin: Optional[str] = Field(default=None, max_length=15)


class BranchRead(BaseModel):
    id: UUID
    organisation_id: UUID
    name: str
    city: Optional[str] = None
    state_code: Optional[str] = None
    gstin: Optional[str] = None
    is_active: bool
    created_at: datetime


class BranchUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    city: Optional[str] = Field(default=None, max_length=100)
    state_code: Optional[str] = Field(default=None, min_length=2, max_length=2)
    gstin: Optional[str] = Field(default=None, max_length=15)


class UserRoleUpdate(BaseModel):
    role: str = Field(..., min_length=3, max_length=50)
    branch_id: Optional[UUID] = None


# ---------------------------------------------------------------------------
# Step 5 — Input sanitisation helpers (re-usable validators)
# ---------------------------------------------------------------------------

def _sanitise_description(v: object) -> str:
    """Strip, length-limit and control-char check for product_description."""
    v = str(v).strip()
    if len(v) > 2000:
        raise ValueError("max length is 2000 characters")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", v):
        raise ValueError("contains invalid control characters")
    return v


def _validate_hsn_code(v: object) -> str:
    """Must be 2-8 decimal digits only."""
    if not re.match(r"^\d{2,8}$", str(v)):
        raise ValueError("must be 2\u20138 digits only")
    return str(v)


def _validate_date(v: object) -> date:
    """Cannot be in the future or more than 10 years in the past."""
    if isinstance(v, str):
        v = date.fromisoformat(v)
    if v > date.today():
        raise ValueError("cannot be in the future")
    if v < date.today() - timedelta(days=3650):
        raise ValueError("cannot be more than 10 years in the past")
    return v


# ---------------------------------------------------------------------------
# Report / filter schemas with sanitised fields
# ---------------------------------------------------------------------------

class ProductLookupRequest(BaseModel):
    """Generic product lookup with sanitised description and hsn_code."""
    product_description: Optional[str] = None
    hsn_code: Optional[str] = None

    @field_validator("product_description", mode="before")
    @classmethod
    def sanitise_description(cls, v: object) -> str | None:
        if v is None:
            return None
        return _sanitise_description(v)

    @field_validator("hsn_code", mode="before")
    @classmethod
    def validate_hsn_code(cls, v: object) -> str | None:
        if v is None:
            return None
        return _validate_hsn_code(v)


class DateRangeFilter(BaseModel):
    """Date range filter schema with past/future guard rails."""
    from_date: Optional[date] = None
    to_date: Optional[date] = None

    @field_validator("from_date", "to_date", mode="before")
    @classmethod
    def validate_dates(cls, v: object) -> date | None:
        if v is None:
            return None
        return _validate_date(v)


class ReportRequest(DateRangeFilter):
    """Full report request schema: date range + optional HSN filter."""
    hsn_code: Optional[str] = None
    product_description: Optional[str] = None

    @field_validator("hsn_code", mode="before")
    @classmethod
    def validate_hsn_code(cls, v: object) -> str | None:
        if v is None:
            return None
        return _validate_hsn_code(v)

    @field_validator("product_description", mode="before")
    @classmethod
    def sanitise_description(cls, v: object) -> str | None:
        if v is None:
            return None
        return _sanitise_description(v)
