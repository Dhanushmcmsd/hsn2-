from __future__ import annotations

import re

# Trade abbreviations (Indian/commercial invoice style). Keys are uppercase tokens.
ABBREV_TRADE: dict[str, str] = {
    "AC": "air conditioner",
    "LED": "light emitting diode",
    "TV": "television",
    "PVC": "polyvinyl chloride",
    "SS": "stainless steel",
    "MS": "mild steel",
    "HDPE": "high density polyethylene",
    "PPE": "personal protective equipment",
    "RO": "reverse osmosis",
    "UPS": "uninterruptible power supply",
}

# Model / SKU suffix like ROYAL BROOM-1036, ITEM-12
_MODEL_SUFFIX_RE = re.compile(r"(?<=[\w])-\d+(?=\s*$|\s+)", re.UNICODE)
# Pack sizes and power (keep text clean for matching)
_SIZE_TOKEN_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:g|gm|gms|kg|kgs|ml|l|ltr|litre|L|w|kw|va|volt|v)\b",
    re.IGNORECASE,
)


def normalize_product_name(text: str) -> str:
    """
    Normalize invoice-style product names: expand common abbreviations,
    strip model-number tails and size tokens, lowercase, drop punctuation.
    """
    raw = (text or "").strip()
    if not raw:
        return ""

    s = _MODEL_SUFFIX_RE.sub("", raw)
    s = _SIZE_TOKEN_RE.sub(" ", s)
    s = re.sub(r"\b\d+\s*x\s*\d+\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d+\s*\+\s*\d+\b", " ", s, flags=re.IGNORECASE)

    tokens = re.findall(r"[\w]+", s, flags=re.UNICODE)
    out: list[str] = []
    for tok in tokens:
        if tok.isdigit():
            continue
        upper = tok.upper()
        if upper in ABBREV_TRADE:
            out.extend(ABBREV_TRADE[upper].lower().split())
        else:
            out.append(tok.lower())

    joined = " ".join(out)
    joined = re.sub(r"[^a-z0-9\s\u0080-\uffff]", " ", joined.lower())
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined
