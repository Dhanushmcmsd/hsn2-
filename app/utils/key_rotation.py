import secrets
import hashlib


def generate_api_key() -> tuple[str, str]:
    """Returns (raw_key, hashed_key)"""
    raw = secrets.token_hex(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()
