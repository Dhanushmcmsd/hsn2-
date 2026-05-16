"""normalizer.py — product name normalisation.

Changes (2026-05-16):
- Added Malayalam / non-ASCII Unicode passthrough guard.
  Script text (Malayalam, Hindi Devanagari, etc.) must NOT be
  processed by ASCII-only regex patterns.  If the input contains
  non-ASCII characters we return it minimally cleaned so downstream
  search layers (brand_lookup -> language_aliases) can handle it.
"""
from __future__ import annotations

import re
import unicodedata

# ── Constants ─────────────────────────────────────────────────────────────────
_SIZE_UNITS = (
    r'(?:G|GM|GMS|KG|KGS|ML|L|LTR|LITRE|LITER|'
    r'PC|PCS|NOS|NO|N|P|IN|MG|OZ|LB|PACK|PKT|BOX|BTL|BOTTLE|TIN|JAR|CAN|SACHET|BAG|POUCH)'
)
_SIZE_PAT = re.compile(
    rf'\b\d+(?:\.\d+)?\s*{_SIZE_UNITS}\b'
    r'|\b\d+\s*X\s*\d+\b'
    r'|\b\d+\s*\+\s*\d+\b'
    r'|\b\d+S\b|\b\d+N\b|\b\d+P\b',
    re.IGNORECASE,
)

_PUNCT_PAT = re.compile(r'[\(\)\[\]\{\}#@\\|\^~`]')
_WS_PAT = re.compile(r'\s+')

# Characters that indicate non-Latin script (Malayalam, Devanagari, etc.)
_NON_ASCII_RE = re.compile(r'[^\x00-\x7F]')

# Common product words that should NOT be stripped even if they look like brand
_STOP_PREFIXES = frozenset({
    'THE', 'A', 'AN', 'AND', 'WITH', 'FOR', 'OF', 'IN', 'AT', 'BY'
})


def _has_script_chars(text: str) -> bool:
    """Return True if text contains non-ASCII (Malayalam/Devanagari/etc.) characters."""
    return bool(_NON_ASCII_RE.search(text))


def normalize_product_name(raw: str) -> str:
    """
    Normalize a raw product description for HSN search.

    Strategy
    --------
    1. If the input contains non-ASCII script characters (Malayalam, Hindi,
       Arabic, etc.) — return it as-is after minimal whitespace cleanup.  The
       language_aliases / kerala_search layers handle script text directly.
    2. For ASCII/Latin text: strip size/unit tokens, collapse whitespace,
       upper-case.  Preserve brand names and descriptive words.
    """
    if not raw:
        return ''

    text = raw.strip()

    # ── Guard: non-ASCII / script input — pass through unchanged ──────────────
    if _has_script_chars(text):
        # Only collapse whitespace; preserve every non-ASCII character exactly
        return _WS_PAT.sub(' ', text).strip()

    # ── ASCII / Latin normalisation path ──────────────────────────────────────
    # 1. Remove packaging punctuation (brackets, special chars)
    text = _PUNCT_PAT.sub(' ', text)

    # 2. Strip size/quantity tokens  (e.g. "500G", "2X200ML", "3+1")
    text = _SIZE_PAT.sub(' ', text)

    # 3. Collapse whitespace and upper-case
    text = _WS_PAT.sub(' ', text).strip().upper()

    # 4. Remove leading stop words ("A ", "THE ") but keep brand first-words
    tokens = text.split()
    # Only strip if the token is a stop word AND there are more tokens after it
    while tokens and tokens[0] in _STOP_PREFIXES and len(tokens) > 1:
        tokens = tokens[1:]

    return ' '.join(tokens)
