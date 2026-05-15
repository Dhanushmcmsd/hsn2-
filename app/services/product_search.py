"""
Product Name Search Layer
Searches the actual product name / trade name column in the DB.
Runs AFTER existing DB/FTS layers and BEFORE FAISS, OR
at whichever position the audit shows is the right gap.
Uses three sub-strategies in sequence, returns on first hit.
"""

import structlog
from rapidfuzz import process, fuzz
from sqlalchemy import text

# Use exact table/column names found in Phase 1 audit
PRODUCT_TABLE = "verified_products"
NAME_COL = "description"
HSN_COL = "hsn_code"
GST_COL = "gst_rate"
DESC_COL = "description"

log = structlog.get_logger()

def _tokenize(query: str) -> list[str]:
    """
    Split query into meaningful tokens.
    Remove size/quantity suffixes: 5g, 500ml, 1kg, 100pc etc.
    Remove tokens shorter than 3 characters.
    e.g. "womans horlicks 500g" → ["womans", "horlicks"]
    e.g. "BOOST HEALTH DRINK" → ["boost", "health", "drink"]
    """
    import re
    q = query.lower().strip()
    q = re.sub(r'\b\d+\s*(g|kg|ml|l|mg|gm|pc|pcs|nos|pack|tab|tabs|caps)\b', '', q)
    return [t for t in q.split() if len(t) >= 3]

async def search_by_product_name(db, query: str) -> dict | None:
    """
    Sub-strategy 1: pg_trgm similarity on product name column.
    Requires pg_trgm extension (checked in Phase 1).
    Tries full query first, then each token separately.
    Returns best match above threshold=0.25, or None.
    """
    tokens = _tokenize(query)
    candidates = []

    for term in [query.lower()] + tokens:
        try:
            rows = await db.execute(text(f"""
                SELECT {NAME_COL}, {HSN_COL}, {GST_COL}, {DESC_COL},
                       similarity({NAME_COL}, :term) AS score
                FROM {PRODUCT_TABLE}
                WHERE similarity({NAME_COL}, :term) > 0.20
                ORDER BY score DESC LIMIT 3
            """), {"term": term})
            candidates.extend(rows.fetchall())
        except Exception as exc:
            log.warning("product_search.search_by_product_name_failed", error=str(exc), query=query[:60])
            return None

    if not candidates:
        return None

    best = max(candidates, key=lambda r: r.score)
    if best.score >= 0.25:
        return _to_dict(best, source="product_trigram")
    return None

async def search_by_token_ilike(db, query: str) -> dict | None:
    """
    Sub-strategy 2: ILIKE per-token search.
    For each token in the query, search for rows where name ILIKE '%token%'.
    Score = number of tokens that matched / total tokens (coverage ratio).
    Returns result only if at least one token matches.
    """
    tokens = _tokenize(query)
    if not tokens:
        return None

    all_hits = {}   # hsn_code → {row, matched_tokens}

    for token in tokens:
        try:
            rows = await db.execute(text(f"""
                SELECT {NAME_COL}, {HSN_COL}, {GST_COL}, {DESC_COL}
                FROM {PRODUCT_TABLE}
                WHERE LOWER({NAME_COL}) LIKE '%' || :token || '%'
                LIMIT 5
            """), {"token": token})
        except Exception as exc:
            log.warning("product_search.search_by_token_ilike_failed", error=str(exc), query=query[:60])
            return None
        for row in rows.fetchall():
            key = getattr(row, HSN_COL)
            if key not in all_hits:
                all_hits[key] = {"row": row, "count": 0}
            all_hits[key]["count"] += 1

    if not all_hits:
        return None

    # Pick the hsn_code with the most token matches
    best_hsn = max(all_hits, key=lambda k: all_hits[k]["count"])
    best = all_hits[best_hsn]
    coverage = best["count"] / len(tokens)

    return _to_dict(best["row"], source="product_ilike", score=coverage)

def search_in_memory(query: str, product_name_cache: list[tuple]) -> dict | None:
    """
    Sub-strategy 3: RapidFuzz in-memory search.
    product_name_cache is loaded at startup: list of (name, hsn_code, gst, desc).
    Tries full query and each token. Uses token_set_ratio scorer.
    Returns match if score >= 65.
    Falls back gracefully if rapidfuzz not installed.
    """
    if not product_name_cache:
        return None

    names = [r[0] for r in product_name_cache]
    tokens = _tokenize(query)
    best_match = None
    best_score = 0

    for term in [query] + tokens:
        result = process.extractOne(
            term, names,
            scorer=fuzz.token_set_ratio,
            score_cutoff=60
        )
        if result and result[1] > best_score:
            best_score = result[1]
            best_match = result

    if best_match:
        idx = names.index(best_match[0])
        row = product_name_cache[idx]
        return {
            "hsn_code": row[1], "gst_rate": row[2],
            "description": row[3], "matched_name": row[0],
            "score": best_score / 100, "source": "product_rapidfuzz"
        }
    return None

def _to_dict(row, source: str, score: float = None) -> dict:
    return {
        "hsn_code": getattr(row, HSN_COL),
        "gst_rate": getattr(row, GST_COL),
        "description": getattr(row, DESC_COL),
        "matched_name": getattr(row, NAME_COL),
        "score": score if score is not None else getattr(row, "score", 0),
        "source": source
    }
