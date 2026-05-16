"""Structured audit logging for GST classify requests (tamper-evident JSONL)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_AUDIT_PATH = Path(__file__).resolve().parents[2] / "logs" / "audit.jsonl"


def _hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


async def log_classify_event(
    *,
    request_id: str,
    api_key: str,
    client_ip: str,
    product_name: str,
    hsn_code: Optional[str],
    gst_rate: Optional[float],
    confidence_score: Optional[int],
    layer_matched: Optional[str],
    response_time_ms: float,
) -> None:
    """Append one tamper-evident audit record for a successful classify response."""
    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "api_key_hash": _hash_api_key(api_key),
        "client_ip": client_ip,
        "product_name": product_name,
        "hsn_code": hsn_code,
        "gst_rate": gst_rate,
        "confidence_score": confidence_score,
        "layer_matched": layer_matched,
        "response_time_ms": round(response_time_ms, 2),
    }
    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _AUDIT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
