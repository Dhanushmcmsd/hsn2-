from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.db_matcher import match_query
from app.services.kerala_aliases import (
    KERALA_ABBREVIATIONS,
    KERALA_ALIAS_MAP,
    KERALA_BRANDS,
)
from app.services.matcher import expand_fmcg_abbreviations, strip_sizes, tokenize

KERALA_FOOD_MAP = {
    "PUTTU": {"search": "puttupodi rice flour", "hsn": "11023000"},
    "AVAL": {"search": "beaten rice poha flattened", "hsn": "19041020"},
    "MATTA": {"search": "matta rice rosematta red rice", "hsn": "10063090"},
    "TAPIOCA": {"search": "cassava tapioca kappa", "hsn": "20081940"},
    "APPAM": {"search": "appam idiyappam rice flour batter", "hsn": "11029090"},
    "KOZHUVA": {"search": "anchovy fish kozhuva sardine", "hsn": "03083020"},
    "PAYASAM": {"search": "payasam mix palada kheer", "hsn": "19019090"},
    "PATHIMUGHAM": {"search": "sarsaparilla hemidesmus herbal", "hsn": "12119099"},
    "SAMBAR PODI": {"search": "sambar masala powder spice", "hsn": "09109100"},
    "RASAM PODI": {"search": "rasam powder spice", "hsn": "09109100"},
    "PUJA OIL": {"search": "lamp oil sesame puja pooja", "hsn": "15180040"},
    "NADAN": {"search": "traditional local country style", "hsn": None},
}

VKC_PATTERN = re.compile(
    r"^VKC\s+"
    r"(?P<collection>[A-Z]+)?\s*"
    r"(?P<model>[A-Z0-9.]+)\s+"
    r"(?P<color>[A-Z.]+)?\s*"
    r"(?P<gender>LAD(?:IES?)?|GENT(?:S)?|KIDS?|INF(?:ANT)?|BOY|BOYS|GIRL|GIRLS|YOUTH)?\s*"
    r"(?P<size>\d{1,2})?",
    re.IGNORECASE,
)


def _normalize_ws(text_value: str) -> str:
    return re.sub(r"\s+", " ", text_value.strip().upper())


def _strip_sizes(text_value: str) -> str:
    return strip_sizes(text_value)


def _extract_alpha_tokens(text_value: str) -> list[str]:
    return re.findall(r"[A-Z]{2,}", _normalize_ws(text_value))


def _token_overlap_score(query: str, description: str) -> float:
    q_tokens = set(tokenize(expand_kerala_query(query)))
    d_tokens = set(tokenize(expand_fmcg_abbreviations(description or "")))
    if not q_tokens or not d_tokens:
        return 0.0
    overlap = len(q_tokens & d_tokens)
    return overlap / max(len(q_tokens), 1)


def _clean_gst(raw_value) -> float:
    if raw_value is None:
        return 0.0
    match = re.search(r"(\d+(?:\.\d+)?)", str(raw_value))
    return float(match.group(1)) if match else 0.0


def _chapter_for(hsn_code: str) -> str:
    digits = re.sub(r"[^0-9]", "", str(hsn_code or ""))
    return digits[:2]


def _alias_to_match(alias: dict, query: str, *, method: str) -> dict:
    score = round(float(alias.get("confidence", 0.85)), 3)
    return {
        "hsn_code": alias["hsn_code"],
        "description": alias["description"],
        "gst_rate": float(alias.get("gst_rate") or 0),
        "score": score,
        "confidence": score,
        "method": method,
        "source": "kerala_aliases",
        "category": alias.get("category"),
        "matched_query": query,
    }


def expand_kerala_query(query: str) -> str:
    normalized = _normalize_ws(query)
    expanded = normalized
    for raw, replacement in sorted(KERALA_ABBREVIATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(raw.upper())}(?![A-Z0-9])")
        expanded = pattern.sub(replacement.upper(), expanded)
    expanded = expand_fmcg_abbreviations(expanded).upper()
    return _normalize_ws(expanded)


def parse_vkc_code(query: str) -> dict | None:
    q_upper = _normalize_ws(query)
    match = VKC_PATTERN.match(q_upper)
    if not match:
        return None
    gender_match = re.search(
        r"\b(LAD(?:IES?)?|LADY|GENT(?:S)?|KIDS?|INF(?:ANT)?|BOY|BOYS|GIRL|GIRLS|YOUTH)\b",
        q_upper,
    )
    gender = (gender_match.group(1) if gender_match else match.group("gender") or "").upper()
    hsn = "64022090" if gender in {"LAD", "LADIES", "LADY"} else "64029990"
    score = 0.87
    return {
        "hsn_code": hsn,
        "description": f"VKC footwear - {q_upper}",
        "gst_rate": 5.0,
        "score": score,
        "confidence": score,
        "method": "kerala_vkc_parser",
        "source": "kerala_aliases",
    }


async def _verified_like_search(
    db: AsyncSession,
    *,
    tokens: list[str] | None = None,
    prefix: str | None = None,
    limit: int = 10,
) -> list[dict]:
    where_parts: list[str] = []
    params: dict[str, object] = {"limit": limit}
    if prefix:
        where_parts.append("vp.description_normalized LIKE :prefix")
        params["prefix"] = prefix
    for idx, token in enumerate(tokens or []):
        where_parts.append(f"vp.description_normalized LIKE :token_{idx}")
        params[f"token_{idx}"] = f"%{token}%"
    if not where_parts:
        return []

    result = await db.execute(
        text(
            f"""
            SELECT vp.description, vp.hsn_code, vp.gst_rate
            FROM verified_products vp
            WHERE {" AND ".join(where_parts)}
            ORDER BY LENGTH(vp.description_normalized) ASC
            LIMIT :limit
            """
        ),
        params,
    )
    return [
        {
            "description": row.description,
            "hsn_code": row.hsn_code,
            "gst_rate": _clean_gst(row.gst_rate),
        }
        for row in result.fetchall()
    ]


def _rerank_verified_rows(
    query: str,
    rows: list[dict],
    *,
    method: str,
    base_score: float,
    chapter_hint: str | None = None,
) -> list[dict]:
    ranked: list[dict] = []
    for row in rows:
        overlap = _token_overlap_score(query, row["description"])
        score = min(0.92, base_score + overlap * 0.22)
        if chapter_hint and _chapter_for(row["hsn_code"]) == chapter_hint:
            score = min(0.92, score + 0.04)
        ranked.append(
            {
                "hsn_code": row["hsn_code"],
                "description": row["description"],
                "gst_rate": row["gst_rate"],
                "score": round(score, 3),
                "confidence": round(score, 3),
                "method": method,
                "source": "verified_products",
            }
        )
    ranked.sort(key=lambda item: (item["score"], -len(item["description"])), reverse=True)
    return ranked


async def _kerala_food_search(query: str, db: AsyncSession) -> list[dict]:
    q_upper = _normalize_ws(query)
    for key, info in sorted(KERALA_FOOD_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if key not in q_upper:
            continue
        search_tokens = [token.upper() for token in info["search"].split() if len(token) >= 4][:3]
        rows = await _verified_like_search(db, tokens=search_tokens, limit=10)
        ranked = _rerank_verified_rows(
            query,
            rows,
            method="kerala_food_verified",
            base_score=0.68,
            chapter_hint=(info["hsn"] or "")[:2] or None,
        )
        if ranked:
            return ranked[:5]
    return []


async def kerala_brand_prefix_search(query: str, db: AsyncSession, *, top_k: int = 5) -> list[dict]:
    q_upper = _normalize_ws(query)
    for brand, metadata in sorted(KERALA_BRANDS.items(), key=lambda item: len(item[0]), reverse=True):
        if not q_upper.startswith(brand):
            continue
        rows = await _verified_like_search(db, prefix=f"{brand}%", limit=12)
        ranked = _rerank_verified_rows(
            query,
            rows,
            method="kerala_brand_prefix",
            base_score=0.62,
            chapter_hint=metadata.get("chapter"),
        )
        if ranked:
            return ranked[:top_k]

        expanded = expand_kerala_query(query)
        if expanded != q_upper:
            result = await match_query(expanded, db, top_k=top_k)
            if result and result[0].get("score", 0) >= 0.5:
                for item in result:
                    item["method"] = f"kerala_brand_{item.get('method', '')}"
                    item["score"] = round(min(0.72, float(item.get("score", 0)) + 0.02), 3)
                    item["confidence"] = item["score"]
                return result[:top_k]
    return []


async def kerala_fallback_search(
    query: str,
    db: AsyncSession,
    *,
    top_k: int = 5,
) -> list[dict]:
    """
    Kerala-specific secondary search layer.

    Invoked when primary passes return confidence < 0.30 or empty results.
    """
    q_upper = _normalize_ws(query)
    q_no_size = _strip_sizes(q_upper)

    if q_upper in KERALA_ALIAS_MAP:
        alias = KERALA_ALIAS_MAP[q_upper]
        return [_alias_to_match(alias, query, method="kerala_alias_exact")]

    for key, alias in sorted(KERALA_ALIAS_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if q_upper.startswith(key) or q_no_size.startswith(key) or (len(key) >= 10 and q_upper.startswith(key[:8])):
            return [_alias_to_match(alias, query, method="kerala_alias_prefix")]

    expanded = expand_kerala_query(query)
    if db is None:
        return []
    if expanded != q_upper:
        result = await match_query(expanded, db, top_k=top_k)
        if result and result[0].get("score", 0) >= 0.45:
            for item in result:
                item["method"] = f"kerala_abbrev_{item.get('method', '')}"
                item["score"] = round(max(0.0, float(item.get("score", 0)) - 0.03), 3)
                item["confidence"] = item["score"]
            return result[:top_k]

    food_rows = await _kerala_food_search(query, db)
    if food_rows:
        return food_rows[:top_k]

    vkc_match = parse_vkc_code(query)
    if vkc_match:
        return [vkc_match]

    brand_rows = await kerala_brand_prefix_search(query, db, top_k=top_k)
    if brand_rows:
        return brand_rows[:top_k]

    q_tokens = [token for token in _extract_alpha_tokens(expanded) if len(token) >= 4]
    if q_tokens:
        rows = await _verified_like_search(db, tokens=q_tokens[:2], limit=20)
        if rows:
            by_hsn = Counter(row["hsn_code"] for row in rows)
            ranked = _rerank_verified_rows(
                query,
                rows,
                method="kerala_verified_fuzzy",
                base_score=0.58,
            )
            for item in ranked:
                item["score"] = round(min(0.82, item["score"] + by_hsn[item["hsn_code"]] * 0.01), 3)
                item["confidence"] = item["score"]
            return ranked[:top_k]

    return []
