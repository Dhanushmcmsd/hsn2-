"""Map gst_classifier.classify() results to /predict and /hsn/batch API shapes."""
from __future__ import annotations

from typing import Any

from app.models.schemas import HSNMatch, PredictResponse
from app.services.hsn_master import canonicalize_hsn

_INVALID_HSN = frozenset({"", "UNKNOWN", "UNCLASSIFIED", "99999999", None})
_MIN_CONFIDENCE = 70


def is_authoritative_classify(result: dict[str, Any]) -> bool:
    """True when classify output is safe to return without legacy fallback."""
    hsn = (result.get("hsn_code") or "").strip()
    if not hsn or hsn in _INVALID_HSN:
        return False
    digits = "".join(c for c in hsn if c.isdigit())
    if len(digits) not in (2, 4, 6, 8):
        return False
    if result.get("gst_rate") is None:
        return False
    conf = int(result.get("confidence_score") or result.get("confidence") or 0)
    if conf < _MIN_CONFIDENCE:
        return False
    if result.get("needs_manual_review") or result.get("review_required"):
        return False
    return True


def _confidence_fraction(result: dict[str, Any]) -> float:
    raw = result.get("confidence_score")
    if raw is None:
        raw = result.get("confidence")
    conf = int(raw or 0)
    if conf > 1:
        return min(1.0, conf / 100.0)
    return float(conf or 0.0)


def _confidence_label(conf: float) -> str:
    if conf >= 0.80:
        return "high"
    if conf >= 0.55:
        return "medium"
    return "low"


def _normalize_hsn_display(code: str | None) -> str:
    if not code:
        return ""
    normalized = canonicalize_hsn(code)
    return normalized or str(code).strip()


def _alternates_to_matches(alternates: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for alt in alternates or []:
        code = _normalize_hsn_display(alt.get("hsn_code"))
        if not code or code in _INVALID_HSN:
            continue
        score = float(alt.get("score") or alt.get("confidence") or 0.5)
        if score > 1:
            score = score / 100.0
        out.append({
            "hsn_code": code,
            "description": alt.get("description") or "",
            "gst_rate": alt.get("gst_rate"),
            "score": round(score, 4),
            "method": alt.get("method") or "alternate",
        })
    return out


def to_batch_result(query: str, result: dict[str, Any]) -> dict[str, Any]:
    """Shape expected by POST /hsn/batch (HSNBatchResult)."""
    if not is_authoritative_classify(result):
        hsn = (result.get("hsn_code") or "").strip()
        if hsn and hsn not in _INVALID_HSN:
            return {
                "query": query,
                "hsn_code": _normalize_hsn_display(hsn),
                "description": result.get("description") or "",
                "gst_rate": result.get("gst_rate"),
                "confidence": _confidence_fraction(result),
                "confidence_label": _confidence_label(_confidence_fraction(result)),
                "match_method": result.get("matched_layer") or result.get("source") or "classify",
                "alternatives": _alternates_to_matches(result.get("alternates")),
                "error": "Needs manual review",
            }
        return {
            "query": query,
            "hsn_code": None,
            "description": result.get("description"),
            "gst_rate": result.get("gst_rate"),
            "confidence": 0.0,
            "confidence_label": "low",
            "match_method": result.get("matched_layer") or "none",
            "alternatives": [],
            "error": "No confident HSN match",
        }

    conf = _confidence_fraction(result)
    return {
        "query": query,
        "hsn_code": _normalize_hsn_display(result.get("hsn_code")),
        "description": result.get("description") or "",
        "gst_rate": float(result["gst_rate"]) if result.get("gst_rate") is not None else None,
        "confidence": conf,
        "confidence_label": _confidence_label(conf),
        "match_method": result.get("matched_layer") or result.get("source") or "classify",
        "alternatives": _alternates_to_matches(result.get("alternates")),
        "error": None,
    }


def to_predict_response(
    request_id: str,
    input_text: str,
    result: dict[str, Any],
    *,
    processing_time_ms: float,
) -> PredictResponse:
    """Build PredictResponse from gst_classifier output."""
    conf_frac = _confidence_fraction(result)
    method = result.get("matched_layer") or result.get("source") or "classify"
    hsn = _normalize_hsn_display(result.get("hsn_code")) or "99999999"
    top = HSNMatch(
        hsn_code=hsn,
        description=result.get("description") or "Not classified",
        score=conf_frac,
        method=method,
        gst_rate=float(result["gst_rate"]) if result.get("gst_rate") is not None else None,
    )
    alts = [
        HSNMatch(
            hsn_code=a["hsn_code"],
            description=a.get("description") or "",
            score=float(a.get("score") or 0),
            method=a.get("method") or "alternate",
            gst_rate=a.get("gst_rate"),
        )
        for a in _alternates_to_matches(result.get("alternates"))
    ]
    needs_review = bool(
        result.get("review_required")
        or result.get("needs_manual_review")
        or conf_frac < 0.55
        or hsn == "99999999"
    )
    return PredictResponse(
        request_id=request_id,
        input_text=input_text,
        top_match=top,
        alternatives=alts,
        confidence=conf_frac,
        confidence_label=_confidence_label(conf_frac),
        needs_review=needs_review,
        processing_time_ms=round(processing_time_ms, 1),
    )
