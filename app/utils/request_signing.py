"""HMAC request signing utilities for B2B API integrity verification."""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional


def sign_request(
    secret: str,
    method: str,
    path: str,
    body: bytes,
    *,
    timestamp: Optional[int] = None,
) -> str:
    """Return hex HMAC-SHA256 signature over method, path, body, and unix timestamp."""
    ts = timestamp if timestamp is not None else int(time.time())
    payload = f"{ts}\n{method.upper()}\n{path}\n".encode("utf-8") + body
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_request_signature(
    secret: str,
    method: str,
    path: str,
    body: bytes,
    signature: str,
    timestamp: int,
    *,
    max_age_seconds: int = 300,
) -> bool:
    """Verify signature and reject requests older than max_age_seconds."""
    now = int(time.time())
    if abs(now - timestamp) > max_age_seconds:
        return False
    expected = sign_request(secret, method, path, body, timestamp=timestamp)
    return hmac.compare_digest(expected, signature)
