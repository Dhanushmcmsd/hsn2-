# Malayalam / Kerala Search Audit Report

**Date:** 2026-05-17  
**Scope:** Production classify pipeline, predict route, multi_layer_search, aliases DB layer.

## Executive summary

| Question | Answer |
|----------|--------|
| Is Malayalam search still active? | **Yes** — via `language_aliases` (ml), `aliases.expand_query`, `kerala_search`, and normalizer script passthrough. |
| Called from `classify()`? | **Partially before this change** — only indirectly via tier-5 `multi_layer_search` and script passthrough. **Now also** via explicit `L0_kerala_retail` + Kerala-expanded verified lookup. |
| Dead vs active? | **Active but split** — not dead; duplicated between `kerala_search` and `language_aliases` / `hsn_master`. |
| Improves Kerala recall? | **Yes** for invoice shorthand, transliterated Malayalam, and `KERALA_ALIAS_MAP` staples. |
| Latency cost? | Kerala layer runs only on classify miss before L1; `aliases.refresh` is lazy (~10 min TTL) and in-memory expansion is ~50µs. |
| Recommendation | **Keep separate Kerala layer** for invoice logic; **merge script terms** into `language_aliases`; use Kerala expansion as preprocess for verified lookup. |

## Call graph / entry points

```
POST /api/v1/classify
  └── gst_classifier.classify()
        ├── normalizer.normalize_product_name()  [Malayalam script passthrough]
        ├── expand_kerala_query() → extra verified_products key
        ├── L0_verified_product
        ├── L0_alias_dict (hsn_master in-memory)
        ├── L0_kerala_retail (kerala_fallback_search)  [NEW]
        ├── L1 brand_aliases
        ├── L3 curated_master
        ├── L4 keyword_category_map
        ├── L5 broad → multi_layer_search
        │     └── aliases.expand_query() → language_aliases (hi/ml/en)
        └── L5 keyword_hsn_search

POST /predict (legacy matcher path)
  └── expand_kerala_query + kerala_fallback_search

main.py legacy match_one Pass 5
  └── kerala_fallback_search
```

## Current weaknesses (pre-fix)

1. **`classify()` did not call `kerala_search`** — Malayalam transliteration map unused on primary API.
2. **Operator precedence bug** in `_finalize_layer_result` — low-confidence tier &lt; 5 could incorrectly set `review_required`.
3. **L0 alias dict early return** skipped `_accept_or_accumulate` — inconsistent tier traces.
4. **Keyword fallback** could pass invalid HSN into `best_guess`.
5. **Fuzzy threshold 0.4** on brand/product pg_trgm — high false-positive risk.
6. **Duplication** — same staples in `kerala_aliases`, `hsn_master`, and DB `language_aliases`.

## Architecture recommendation

1. **Preprocess (cheap):** `expand_kerala_query` + `fix_retail_typos` + POS expansion before any DB tier.
2. **Authoritative (high confidence):** `KERALA_ALIAS_MAP`, `language_aliases` exact (ml script), `hsn_master` retail aliases.
3. **Fuzzy (review flagged):** pg_trgm with floors ≥ 0.55 product / 0.65 brand on classify path only.
4. **Do not remove `kerala_search`** — VKC parser, food map, and invoice abbreviations are not in `language_aliases`.

## Changes made in this pass

- Fixed review precedence; alias path uses `_accept_or_accumulate`; kw HSN validation.
- Raised classify fuzzy floors; centralized constants.
- Wired `L0_kerala_retail` + Kerala-expanded verified retry into `classify()`.
- Retail typo fixes, transliteration entries, `hsn_master` store-name aliases.
- Regression tests in `tests/test_gst_classifier_production_fixes.py`.

## Performance notes

- Malayalam script queries: no extra regex work (passthrough).
- `kerala_fallback_search`: O(n) over alias maps in-memory; DB only on miss — typically &lt;5 ms in-memory, 20–80 ms with DB.
- `aliases.refresh`: amortized; not per-request on hot path after warm-up.
- Not run on cache hit (tier 0).

## Remaining risks

- Romanized Malayalam outside transliteration map still depends on DB `language_aliases` seed coverage.
- `kerala_abbrev_*` DB matches capped below authoritative unless score ≥ 0.72.
- SQLite dev DB lacks `language_aliases` / pg_trgm — classify Kerala DB paths noop.

## SQLite vs Neon parity (local dev)

| Capability | SQLite (`hsn_dev.db`) | Neon / Postgres |
|------------|----------------------|-----------------|
| `language_aliases` table | Not created (Alembic skips PG DDL) | Full table + GIN trgm |
| `pg_trgm` fuzzy | Unavailable | Available |
| `aliases.expand_query` fuzzy resolver | Skipped (no table) | Active |
| Kerala JSON fallback | `data/kerala_retail_aliases.json` loaded in-memory when index empty | Optional; DB seed preferred |
| Classify fuzzy floors | In-memory Kerala + `KERALA_ALIAS_MAP` only | Full stack at 0.65 brand / 0.55 product |

**Scripts**

- `python scripts/diagnose_db_environment.py` — dialect, pg_trgm, alias counts, Kerala corpus sample
- `python scripts/seed_kerala_language_aliases.py` — upsert `data/kerala_retail_aliases.json` (Postgres only)
- `LOG_LEVEL=debug python scripts/test_client_excel.py --neon --excel kerala_batch.xlsx --sample 500`

**Preprocess single path:** `app.services.retail_preprocess.preprocess_retail_query()` used by classify, predict, and Excel smoke tests.

## Next upgrades

1. Seed user example Malayalam script terms (മഞ്ഞൾപൊടി, ചായപ്പൊടി) into `language_aliases` with english_term.
2. Batch-sync `KERALA_ALIAS_MAP` → Neon via `scripts/seed_aliases.py`.
3. Client Excel scoring script before/after on Kerala JSON batch.
4. Index high-weight `language_aliases.term_normalized` for script exact match without fuzzy.
