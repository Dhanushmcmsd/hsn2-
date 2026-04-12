from app.models.schemas import PredictResponse, HSNMatch


def fallback_response(text: str, request_id: str) -> PredictResponse:
    return PredictResponse(
        request_id=request_id,
        input_text=text,
        top_match=HSNMatch(hsn_code="9999", description="Miscellaneous", score=0.0, method="fallback"),
        alternatives=[],
        confidence=0.0,
        confidence_label="low",
        needs_review=True,
        processing_time_ms=0.0,
    )
