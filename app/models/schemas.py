from __future__ import annotations
from pydantic import BaseModel, Field


class PredictRequest(BaseModel):
    text: str = Field(..., min_length=2, max_length=500, description="Product description")


class HSNMatch(BaseModel):
    hsn_code: str
    description: str
    score: float
    method: str = "semantic"


class PredictResponse(BaseModel):
    request_id: str
    input_text: str
    top_match: HSNMatch
    alternatives: list[HSNMatch]
    confidence: float
    confidence_label: str
    needs_review: bool
    processing_time_ms: float


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
