from __future__ import annotations

import re

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.hsn_master import canonicalize_hsn
from app.services.matcher import SYNONYMS, expand_fmcg_abbreviations, tokenize

log = structlog.get_logger()

_HSN_HAS_CATEGORY: bool | None = None


def _rerank_matches(query: str, matches: list[dict], *, top_k: int) -> list[dict]:
    if len(matches) <= 1:
        return matches[:top_k]
    try:
        from app.services.nlp import extract_entities
        from app.services.reranker import get_reranker

        reranker = get_reranker()
        entities = extract_entities(query)
        return reranker.rerank(
            query,
            matches[: top_k * 2],
            top_k=top_k,
            query_entities=entities,
        )
    except Exception as exc:
        log.warning("db_matcher.reranker_failed", error=str(exc))
        return matches[:top_k]


def _normalize_hsn(code: str) -> str:
    normalized = canonicalize_hsn(code)
    return normalized or str(code or "").strip()


async def _probe_hsn_category(db: AsyncSession) -> bool:
    global _HSN_HAS_CATEGORY
    if _HSN_HAS_CATEGORY is not None:
        return _HSN_HAS_CATEGORY
    try:
        await db.execute(text("SELECT category FROM hsn_codes LIMIT 0"))
        _HSN_HAS_CATEGORY = True
    except Exception:
        _HSN_HAS_CATEGORY = False
    return _HSN_HAS_CATEGORY


def _build_enhanced_tsquery(tokens: list[str], *, operator: str = "&") -> str:
    cleaned = [re.sub(r"[^a-z]", "", token.lower()) for token in tokens[:8]]
    cleaned = [token for token in cleaned if len(token) >= 2]
    if not cleaned:
        return ""

    terms: list[str] = []
    last_index = min(len(cleaned), 6) - 1
    for idx, token in enumerate(cleaned[:6]):
        variants = [token] + [
            synonym.lower()
            for synonym in SYNONYMS.get(token, [])
            if " " not in synonym and len(synonym) >= 3
        ]
        variants = list(dict.fromkeys(re.sub(r"[^a-z]", "", value) for value in variants))
        variants = [variant for variant in variants if len(variant) >= 2]
        if not variants:
            continue
        if idx == last_index:
            variants = [f"{variant}:*" for variant in variants]
        terms.append(f"({' | '.join(variants)})" if len(variants) > 1 else variants[0])
    return f" {operator} ".join(terms)


def _build_prefix_filter_clause(prefixes: list[str], *, alias: str = "h") -> tuple[str, dict[str, str]]:
    cleaned = [re.sub(r"[^0-9]", "", prefix) for prefix in prefixes if prefix]
    cleaned = [prefix for prefix in dict.fromkeys(cleaned) if len(prefix) >= 2]
    if not cleaned:
        return "", {}

    clause_parts = [f"{alias}.hsn_code LIKE :prefix_{idx}" for idx in range(len(cleaned))]
    params = {f"prefix_{idx}": f"{prefix}%" for idx, prefix in enumerate(cleaned)}
    return " AND (" + " OR ".join(clause_parts) + ")", params


async def _pass1b_prefix_code(query: str, db: AsyncSession) -> list[dict]:
    digit_match = re.search(r"\b(\d{4,8})\b", query)
    if not digit_match:
        return []

    result = await db.execute(
        text("""
            SELECT h.hsn_code, h.description, COALESCE(h.gst_rate, 0) AS gst_rate
            FROM hsn_codes h
            WHERE h.hsn_code LIKE :prefix
            ORDER BY LENGTH(h.hsn_code) ASC, h.hsn_code ASC
            LIMIT 5
        """),
        {"prefix": digit_match.group(1) + "%"},
    )
    rows = result.fetchall()
    return [
        {
            "hsn_code": _normalize_hsn(row.hsn_code),
            "description": row.description,
            "gst_rate": float(row.gst_rate or 0),
            "score": round(max(0.72, 0.98 - idx * 0.08), 3),
            "method": "prefix_code",
            "source": "hsn_codes",
        }
        for idx, row in enumerate(rows)
    ]


async def _pass2_fts(
    query: str,
    tokens: list[str],
    db: AsyncSession,
    *,
    operator: str,
    chapter_hints: list[str] | None = None,
) -> list[dict]:
    ts_query = _build_enhanced_tsquery(tokens, operator=operator)
    if not ts_query:
        return []

    has_category = await _probe_hsn_category(db)
    if has_category:
        category_select = "COALESCE(h.category, '') AS category,"
        weighted_vector = (
            "setweight(to_tsvector('english', h.description), 'A') || "
            "setweight(to_tsvector('english', COALESCE(h.category, '')), 'B')"
        )
    else:
        category_select = "'' AS category,"
        weighted_vector = "setweight(to_tsvector('english', h.description), 'A')"

    domain_clause, domain_params = _build_prefix_filter_clause(chapter_hints or [])

    try:
        result = await db.execute(
            text(f"""
                SELECT
                    h.hsn_code,
                    h.description,
                    COALESCE(h.gst_rate, 0) AS gst_rate,
                    {category_select}
                    ts_rank_cd(
                        {weighted_vector},
                        query_ts,
                        32
                    ) AS rank
                FROM hsn_codes h
                CROSS JOIN to_tsquery('english', :q) query_ts
                WHERE {weighted_vector} @@ query_ts
                {domain_clause}
                ORDER BY rank DESC, h.hsn_code ASC
                LIMIT 20
            """),
            {"q": ts_query, **domain_params},
        )
    except Exception as exc:
        log.info("db_matcher.pass2_unavailable", error=str(exc))
        return []

    rows = result.fetchall()
    if not rows:
        return []

    ranked: list[dict] = []
    for row in rows:
        desc_tokens = set(tokenize(expand_fmcg_abbreviations(row.description or "")))
        overlap = len(set(tokens) & desc_tokens)
        lexical_bonus = min(0.35, overlap * 0.08)
        score = min(0.96, float(row.rank or 0) * 2.8 + lexical_bonus + 0.16)
        ranked.append(
            {
                "hsn_code": _normalize_hsn(row.hsn_code),
                "description": row.description,
                "gst_rate": float(row.gst_rate or 0),
                "score": round(score, 3),
                "method": "fulltext_fts",
                "source": "hsn_codes",
            }
        )
    return ranked


async def _pass4_ilike(
    tokens: list[str],
    db: AsyncSession,
    *,
    chapter_hints: list[str] | None = None,
) -> list[dict]:
    if not tokens:
        return []

    candidates: dict[str, dict] = {}
    domain_clause, domain_params = _build_prefix_filter_clause(chapter_hints or [])
    for token in tokens[:4]:
        if len(token) < 3:
            continue
        try:
            result = await db.execute(
                text("""
                    SELECT h.hsn_code, h.description, COALESCE(h.gst_rate, 0) AS gst_rate
                    FROM hsn_codes h
                    WHERE LOWER(h.description) LIKE :pattern
                    """ + domain_clause + """
                    LIMIT 20
                """),
                {"pattern": f"%{token.lower()}%", **domain_params},
            )
        except Exception as exc:
            log.info("db_matcher.pass4_unavailable", error=str(exc))
            return []

        for row in result.fetchall():
            key = _normalize_hsn(row.hsn_code)
            current = candidates.get(key)
            if not current:
                candidates[key] = {
                    "hsn_code": key,
                    "description": row.description,
                    "gst_rate": float(row.gst_rate or 0),
                    "score": 0.22,
                    "method": "keyword_ilike",
                    "source": "hsn_codes",
                    "_hits": 0,
                }
                current = candidates[key]
            current["_hits"] += 1
            current["score"] = min(0.72, current["score"] + 0.12)

    ranked = sorted(candidates.values(), key=lambda item: (item["_hits"], item["score"]), reverse=True)
    for item in ranked:
        item["score"] = round(item["score"], 3)
        item.pop("_hits", None)
    return ranked[:5]


async def match_query(query: str, db: AsyncSession, *, top_k: int = 5) -> list[dict]:
    q = query.strip()
    if not q:
        return []

    expanded = expand_fmcg_abbreviations(q)
    tokens = tokenize(expanded)
    chapter_hints: list[str] = []
    try:
        from app.services.nlp import entities_to_search_boost, extract_entities

        entities = extract_entities(q)
        nlp_boost = entities_to_search_boost(entities)
        chapter_hints = nlp_boost["chapter_hints"]
        if nlp_boost["boost_terms"]:
            tokens = list(dict.fromkeys(tokens + nlp_boost["boost_terms"]))
    except ImportError:
        pass

    if re.fullmatch(r"\d{4,8}", q):
        normalized_q = _normalize_hsn(q)
        result = await db.execute(
            text("""
                SELECT h.hsn_code, h.description, COALESCE(h.gst_rate, 0) AS gst_rate
                FROM hsn_codes h
                WHERE h.hsn_code = :code
                LIMIT 1
            """),
            {"code": normalized_q},
        )
        row = result.fetchone()
        if row:
            return [{
                "hsn_code": _normalize_hsn(row.hsn_code),
                "description": row.description,
                "gst_rate": float(row.gst_rate or 0),
                "score": 1.0,
                "method": "exact_code",
                "source": "hsn_codes",
            }]

    prefix_rows = await _pass1b_prefix_code(expanded, db)
    if prefix_rows:
        return prefix_rows[:top_k]

    rows = await _pass2_fts(expanded, tokens, db, operator="&", chapter_hints=chapter_hints)
    if not rows and len(tokens) > 1:
        rows = await _pass2_fts(expanded, tokens, db, operator="|", chapter_hints=chapter_hints)
    if rows:
        return _rerank_matches(query, rows, top_k=top_k)

    return _rerank_matches(
        query,
        await _pass4_ilike(tokens, db, chapter_hints=chapter_hints),
        top_k=top_k,
    )
