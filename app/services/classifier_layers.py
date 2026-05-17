"""Layered HSN/GST resolution helpers for the classify pipeline.

Maps to product layers (highest priority first):
  L1 — brand_aliases
  L2 — verified_products
  L3 — hsn_master (curated goods) / service_master (SAC)
  L4 — hsn_codes + gst_rate_history (tariff fallback)
  L5 — controlled fuzzy (pg_trgm)
"""
from __future__ import annotations

import re
from typing import Any, Literal

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

CodeType = Literal["HSN", "SAC"]
TaxSemantics = Literal["igst_only", "combined", "unknown"]

FUZZY_MIN_AUTHORITATIVE = 70
TARIFF_MIN_CONFIDENCE = 55
CURATED_EXACT_CONFIDENCE = 92
CURATED_FUZZY_CONFIDENCE = 80

_DIGITS_RE = re.compile(r"[^0-9]")


def digits_only(code: str) -> str:
    return _DIGITS_RE.sub("", code or "")


def code_type_for(code: str, *, explicit_kind: str | None = None) -> CodeType:
    if explicit_kind in ("HSN", "SAC"):
        return explicit_kind  # type: ignore[return-value]
    d = digits_only(code)
    if d.startswith("99") and len(d) in (4, 6):
        return "SAC"
    return "HSN"


def is_sac_code(code: str) -> bool:
    d = digits_only(code)
    return d.startswith("99") and len(d) in (4, 6)


def normalize_display_code(code: str, *, code_type: CodeType | None = None) -> str:
    """Never zero-pad SAC headings into fake 8-digit HSN."""
    d = digits_only(code)
    if not d:
        return code
    ct = code_type or code_type_for(d)
    if ct == "SAC" and len(d) <= 6:
        return d[:6] if len(d) == 6 else d[:4]
    if len(d) == 8:
        return d
    if len(d) in (2, 4, 6):
        return d.ljust(8, "0") if ct == "HSN" else d
    return d


# ---------------------------------------------------------------------------
# Tax enrichment (Policy 1: igst_only + cess_rate on master)
# ---------------------------------------------------------------------------

_ENRICH_GOODS_SQL = text("""
    SELECT hm.hsn_code, hm.description, hm.gst_rate, hm.cess_applicable,
           hm.cess_rate, hm.rate_semantics, hm.scope, hm.code_kind,
           hm.verified_source,
           h.gst_rate AS history_gst
    FROM hsn_master hm
    LEFT JOIN gst_rate_history h
      ON h.hsn_code = hm.hsn_code AND h.effective_to IS NULL
    WHERE hm.hsn_code = :code
      AND hm.is_active IS NOT FALSE
    LIMIT 1
""")

_ENRICH_SAC_SQL = text("""
    SELECT sm.sac_code, sm.description, sm.gst_rate, sm.verified_source
    FROM service_master sm
    WHERE sm.sac_code = :code
      AND sm.is_active IS NOT FALSE
    LIMIT 1
""")

_ENRICH_TARIFF_SQL = text("""
    SELECT c.hsn_code, c.description, c.gst_rate AS tariff_gst,
           c.igst_rate, c.cess,
           h.gst_rate AS history_gst
    FROM hsn_codes c
    LEFT JOIN gst_rate_history h
      ON h.hsn_code = c.hsn_code AND h.effective_to IS NULL
    WHERE c.hsn_code = :code
    LIMIT 1
""")

_ENRICH_CODES_ONLY_SQL = text("""
    SELECT hsn_code, description, gst_rate
    FROM hsn_codes
    WHERE hsn_code = :code
    LIMIT 1
""")


def _effective_total_tax(
    gst_rate: float | None,
    cess_rate: float | None,
    *,
    tax_semantics: TaxSemantics,
    history_gst: float | None = None,
) -> float | None:
    if gst_rate is None:
        return history_gst
    if tax_semantics == "igst_only" and cess_rate:
        return round(gst_rate + cess_rate, 4)
    if tax_semantics == "combined":
        return gst_rate
    if history_gst is not None and history_gst > gst_rate:
        return float(history_gst)
    return gst_rate


async def enrich_tax_metadata(
    db: AsyncSession,
    code: str,
    *,
    partial: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach code_type, tax_semantics, cess_rate, effective_total_tax, rate_conflict."""
    partial = dict(partial or {})
    d = digits_only(code)
    ct: CodeType = code_type_for(d, explicit_kind=partial.get("code_kind"))
    display_code = normalize_display_code(code, code_type=ct)
    out: dict[str, Any] = {
        "hsn_code": display_code,
        "code_type": ct,
        "tax_semantics": "unknown",
        "cess_rate": None,
        "effective_total_tax": None,
        "rate_conflict": False,
        "trust_level": partial.get("trust_level", "unknown"),
    }
    out.update({k: v for k, v in partial.items() if k not in out or partial[k] is not None})

    try:
        if ct == "SAC" and len(d) <= 6:
            row = (await db.execute(_ENRICH_SAC_SQL, {"code": d[:6] if len(d) == 6 else d[:4]})).mappings().first()
            if not row:
                row = (await db.execute(_ENRICH_SAC_SQL, {"code": d[:4]})).mappings().first()
            if row:
                out["description"] = out.get("description") or row["description"]
                out["gst_rate"] = float(row["gst_rate"]) if row["gst_rate"] is not None else out.get("gst_rate")
                out["cess_applicable"] = False
                out["tax_semantics"] = "combined"
                out["effective_total_tax"] = out["gst_rate"]
                out["matched_source_table"] = out.get("matched_source_table") or "service_master"
                return out
        elif len(d) == 8:
            row = (await db.execute(_ENRICH_GOODS_SQL, {"code": d})).mappings().first()
            if row:
                semantics = (row.get("rate_semantics") or "igst_only") if row.get("rate_semantics") else "igst_only"
                out["tax_semantics"] = semantics
                igst = float(row["gst_rate"]) if row["gst_rate"] is not None else out.get("gst_rate")
                if igst is not None:
                    out["gst_rate"] = igst
                cess_r = row.get("cess_rate")
                if cess_r is not None:
                    out["cess_rate"] = float(cess_r)
                out["cess_applicable"] = bool(row.get("cess_applicable")) or bool(out.get("cess_rate"))
                hist = float(row["history_gst"]) if row.get("history_gst") is not None else None
                out["effective_total_tax"] = _effective_total_tax(
                    out.get("gst_rate"), out.get("cess_rate"),
                    tax_semantics=semantics, history_gst=hist,
                )
                if hist is not None and out.get("gst_rate") is not None:
                    master_gst = float(out["gst_rate"])
                    if abs(hist - master_gst) > 0.01:
                        if out.get("cess_rate") and abs(
                            hist - (master_gst + float(out["cess_rate"]))
                        ) < 0.02:
                            pass
                        elif master_gst == 0.0 and hist in (5.0, 5):
                            # Nil-rated CBIC master vs legacy 5% invoice history — log only.
                            log.debug(
                                "classifier.nil_rated_history_skew",
                                code=d,
                                master=master_gst,
                                history=hist,
                            )
                        elif abs(hist - master_gst) > 0.01:
                            out["rate_conflict"] = True
                            log.warning(
                                "classifier.rate_conflict",
                                code=d,
                                master=master_gst,
                                history=hist,
                            )
                out["description"] = out.get("description") or row.get("description")
                out["matched_source_table"] = out.get("matched_source_table") or "hsn_master"
                return out
            row = (await db.execute(_ENRICH_TARIFF_SQL, {"code": d})).mappings().first()
            if row:
                tariff_gst = row.get("tariff_gst") or row.get("history_gst")
                if tariff_gst is not None:
                    out["gst_rate"] = float(tariff_gst)
                out["tax_semantics"] = "combined"
                out["effective_total_tax"] = float(row["history_gst"]) if row.get("history_gst") is not None else out.get("gst_rate")
                out["trust_level"] = out.get("trust_level") or "tariff_fallback"
                out["matched_source_table"] = out.get("matched_source_table") or "hsn_codes"
                return out
    except Exception as exc:
        log.debug("classifier.enrich_failed", code=code, error=str(exc)[:80])

    if len(d) == 8 and out.get("gst_rate") is None:
        try:
            row = (await db.execute(_ENRICH_CODES_ONLY_SQL, {"code": d})).mappings().first()
            if row:
                if row.get("gst_rate") is not None:
                    out["gst_rate"] = float(row["gst_rate"])
                out["description"] = out.get("description") or row.get("description")
                out["matched_source_table"] = out.get("matched_source_table") or "hsn_codes"
                out["tax_semantics"] = "combined"
        except Exception as exc:
            log.debug("classifier.enrich_codes_only_failed", code=code, error=str(exc)[:80])

    if out.get("gst_rate") is None and len(d) >= 2:
        from app.services.hsn_master import lookup_tariff_gst

        csv_gst = lookup_tariff_gst(d)
        if csv_gst is not None:
            out["gst_rate"] = csv_gst
            out["tax_semantics"] = "combined"
            out["matched_source_table"] = out.get("matched_source_table") or "hsn_codes_csv"

    if out.get("gst_rate") is not None:
        out["effective_total_tax"] = out.get("effective_total_tax") or out["gst_rate"]
    return out


# ---------------------------------------------------------------------------
# Layer 3 — Curated master (goods only; 8-digit)
# ---------------------------------------------------------------------------

_CURATED_EXACT_SQL = text("""
    SELECT hm.hsn_code, hm.description, hm.gst_rate, hm.cess_applicable,
           hm.cess_rate, hm.rate_semantics, hm.scope, hm.code_kind,
           hm.verified_source
    FROM hsn_master hm
    WHERE hm.is_active IS NOT FALSE
      AND COALESCE(hm.code_kind, 'HSN') = 'HSN'
      AND length(hm.hsn_code) = 8
      AND hm.hsn_code = :code
    LIMIT 1
""")

_CURATED_FUZZY_SQL = text("""
    SELECT hm.hsn_code, hm.description, hm.gst_rate, hm.cess_applicable,
           hm.cess_rate, hm.rate_semantics, hm.scope, hm.code_kind,
           hm.verified_source,
           similarity(lower(hm.description), lower(:q)) AS sim
    FROM hsn_master hm
    WHERE hm.is_active IS NOT FALSE
      AND COALESCE(hm.code_kind, 'HSN') = 'HSN'
      AND length(hm.hsn_code) = 8
      AND similarity(lower(hm.description), lower(:q)) > 0.38
    ORDER BY
      CASE hm.scope
        WHEN 'curated_core' THEN 0
        WHEN 'phase1_fm_direct' THEN 1
        ELSE 2
      END,
      sim DESC
    LIMIT 3
""")


async def layer_curated_master(
    db: AsyncSession,
    query_norm: str,
    raw_q: str,
) -> dict[str, Any] | None:
    d = digits_only(query_norm)
    if len(d) == 8:
        try:
            row = (await db.execute(_CURATED_EXACT_SQL, {"code": d})).mappings().first()
            if row:
                return await _curated_hit(db, row, confidence=CURATED_EXACT_CONFIDENCE, match_kind="exact_code")
        except Exception as exc:
            log.debug("classifier.curated_exact_failed", error=str(exc)[:80])

    try:
        from app.services.normalizer import normalize_product_name
        fuzzy_q = normalize_product_name(raw_q).lower() or raw_q.lower()
        rows = (await db.execute(_CURATED_FUZZY_SQL, {"q": fuzzy_q})).mappings().all()
    except Exception as exc:
        log.debug("classifier.curated_fuzzy_failed", error=str(exc)[:80])
        return None

    if not rows:
        return None
    best = rows[0]
    sim = float(best.get("sim") or 0.0)
    conf = CURATED_FUZZY_CONFIDENCE if sim > 0.5 else max(65, int(sim * 100))
    return await _curated_hit(db, best, confidence=conf, match_kind="fuzzy_description")


async def _curated_hit(
    db: AsyncSession,
    row: Any,
    *,
    confidence: int,
    match_kind: str,
) -> dict[str, Any]:
    scope = row.get("scope") or "curated_core"
    verified = scope in ("curated_core", "phase1_fm_direct") or bool(row.get("verified_source"))
    base = {
        "hsn_code": row["hsn_code"],
        "description": row["description"],
        "gst_rate": float(row["gst_rate"]) if row.get("gst_rate") is not None else None,
        "cess_applicable": bool(row.get("cess_applicable")),
        "confidence": confidence,
        "tier_used": 3,
        "source": f"curated_master_{match_kind}",
        "verified": verified,
        "matched_layer": "L3_curated_master",
        "matched_source_table": "hsn_master",
        "code_kind": "HSN",
        "trust_level": "curated",
        "alternates": [],
    }
    return await enrich_tax_metadata(db, row["hsn_code"], partial=base)


# ---------------------------------------------------------------------------
# Layer 4 — Tariff fallback (hsn_codes + active history)
# ---------------------------------------------------------------------------

_TARIFF_TRGM_SQL = text("""
    SELECT c.hsn_code, c.description,
           COALESCE(h.gst_rate, c.gst_rate::float8, c.igst_rate::float8) AS gst_rate,
           c.cess,
           similarity(lower(COALESCE(c.description, '')), lower(:q)) AS sim,
           (SELECT COUNT(*)::int FROM verified_products vp WHERE vp.hsn_code = c.hsn_code) AS product_volume
    FROM hsn_codes c
    LEFT JOIN gst_rate_history h
      ON h.hsn_code = c.hsn_code AND h.effective_to IS NULL
    WHERE COALESCE(c.is_active, TRUE) = TRUE
      AND length(c.hsn_code) = 8
      AND similarity(lower(COALESCE(c.description, '')), lower(:q)) > 0.32
    ORDER BY product_volume DESC, sim DESC
    LIMIT 3
""")


async def layer_tariff_fallback(
    db: AsyncSession,
    raw_q: str,
) -> dict[str, Any] | None:
    try:
        from app.services.inverted_index import search as inverted_search
    except Exception:
        inverted_search = None

    hits: list[dict[str, Any]] = []
    if inverted_search is not None:
        try:
            hits = await inverted_search(db, raw_q, limit=3)
        except Exception as exc:
            log.debug("classifier.tariff_inverted_failed", error=str(exc)[:80])

    if not hits:
        try:
            from app.services.normalizer import normalize_product_name
            tariff_q = normalize_product_name(raw_q).lower() or raw_q.lower()
            rows = (await db.execute(_TARIFF_TRGM_SQL, {"q": tariff_q})).mappings().all()
            for r in rows:
                sim = float(r.get("sim") or 0.0)
                hits.append({
                    "hsn_code": r["hsn_code"],
                    "description": r["description"] or "",
                    "gst_rate": float(r["gst_rate"]) if r.get("gst_rate") is not None else None,
                    "score": sim,
                    "method": "tariff_trgm",
                })
        except Exception as exc:
            log.debug("classifier.tariff_trgm_failed", error=str(exc)[:80])
            return None

    if not hits:
        return None

    best = hits[0]
    code = (best.get("hsn_code") or "").strip()
    if not code or len(digits_only(code)) != 8:
        return None

    score = float(best.get("score") or 0.0)
    confidence = min(75, max(TARIFF_MIN_CONFIDENCE, int(score * 100) if score <= 1 else int(score)))

    alternates = [
        {"hsn_code": h.get("hsn_code"), "description": h.get("description"), "score": h.get("score")}
        for h in hits[1:3]
        if h.get("hsn_code")
    ]

    base = {
        "hsn_code": code,
        "description": best.get("description") or "",
        "gst_rate": best.get("gst_rate"),
        "cess_applicable": False,
        "confidence": confidence,
        "tier_used": 5,
        "source": best.get("method") or "tariff_fallback",
        "verified": False,
        "matched_layer": "L4_tariff_fallback",
        "matched_source_table": "hsn_codes",
        "code_kind": "HSN",
        "trust_level": "tariff_fallback",
        "alternates": alternates,
    }
    enriched = await enrich_tax_metadata(db, code, partial=base)
    enriched["review_required"] = confidence < FUZZY_MIN_AUTHORITATIVE
    return enriched
