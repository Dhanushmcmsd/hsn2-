from app.config import settings


def score_result(raw_score: float) -> tuple[float, str]:
    confidence = round(min(max(raw_score, 0.0), 1.0), 4)
    if confidence >= settings.CONFIDENCE_HIGH:
        label = "high"
    elif confidence >= settings.CONFIDENCE_MEDIUM:
        label = "medium"
    else:
        label = "low"
    return confidence, label
