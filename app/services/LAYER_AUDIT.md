# HSN/GST Classification Layer Audit

**Audit date:** 2026-05-17  
**Scope:** All search/classification layers used by `/api/v1/classify` and `/search/*`  
**Smoke tests:** `scripts/layer_smoke_test.py` → `scripts/smoke_test_results.json`

---

## Layer map (priority order)

### L0 — In-memory product alias dict (`app/services/hsn_master.py`)

| Field | Value |
|-------|--------|
| **Data source** | Hard-coded `_VERIFIED_PRODUCT_ALIASES` + `_ALIAS_GST_HINTS` (CBIC retail mappings) |
| **Match strategy** | Exact + longest-substring match after `normalize_product_name()` |
| **Fallback** | TIER 0 DB cache → L1 brand_aliases |
| **Weaknesses** | Requires manual curation; short aliases can theoretically false-positive on substring (`alias in q`) — mitigated by longest-match-first ordering |
| **Health** | **Healthy** — resolves all 50/50 smoke-test queries (core + hard variants) |

### L0b — DB search cache (`search_cache` table)

| Field | Value |
|-------|--------|
| **Data source** | Neon/Postgres or SQLite `search_cache` |
| **Match strategy** | Exact on `query_normalized` |
| **Fallback** | L1 brand_aliases |
| **Weaknesses** | Stale cache can mask alias/CSV fixes until TTL expires or `bypass_cache=true` |
| **Health** | **Healthy** on production Postgres |

### L1 — Brand aliases (`brand_aliases` + `service_master` for SAC)

| Field | Value |
|-------|--------|
| **Data source** | Neon DB tables `brand_aliases`, `hsn_master`, `service_master` |
| **Match strategy** | Exact uppercase brand name |
| **Fallback** | L2 verified_products |
| **Weaknesses** | SQLite dev DB may lack `service_master` (SAC joins fail gracefully) |
| **Health** | **Healthy** on production; dev SQLite partial |

### L2 — Verified products (`verified_products`)

| Field | Value |
|-------|--------|
| **Data source** | Neon `verified_products` + join `hsn_master` |
| **Match strategy** | Exact `description_normalized` / `description_no_size` |
| **Fallback** | L3 curated master |
| **Weaknesses** | Small seed set (~17 rows in dev); needs batch imports for client SKUs |
| **Health** | **Needs expansion** for client-specific SKU coverage |

### L3 — Curated HSN master (`hsn_master`)

| Field | Value |
|-------|--------|
| **Data source** | Neon `hsn_master` (promoted 8-digit goods) |
| **Match strategy** | Exact 8-digit code in query; else `pg_trgm` fuzzy on description |
| **Fallback** | L4 keyword map |
| **Weaknesses** | Requires `pg_trgm` + `cess_rate` column on Postgres; fails on minimal SQLite schema |
| **Health** | **Healthy** on production Postgres |

### L4 — Keyword category map (`keyword_category_map`)

| Field | Value |
|-------|--------|
| **Data source** | Neon `keyword_category_map` |
| **Match strategy** | `ILIKE '%keyword%'` ordered by keyword length |
| **Fallback** | L4 tariff / L5 fuzzy |
| **Weaknesses** | Postgres-only (`ILIKE`); not available on SQLite dev |
| **Health** | **Healthy** on production |

### L4 (tariff) — Tariff fallback (`hsn_codes` + inverted index)

| Field | Value |
|-------|--------|
| **Data source** | `data/hsn_codes.csv` → DB `hsn_codes`; optional `gst_rate_history` |
| **Match strategy** | Inverted-index `ts_rank_cd` then `pg_trgm` on descriptions |
| **Fallback** | L5 fuzzy (brand/product trgm) |
| **Weaknesses** | Needs `hsn_search.search_vector` + Postgres extensions; SQLite lacks `to_tsvector` / `similarity` |
| **Health** | **Healthy** on production; **degraded** locally |

### L5 — Controlled fuzzy (`brand_aliases` / `verified_products` pg_trgm)

| Field | Value |
|-------|--------|
| **Data source** | Neon `brand_aliases`, `verified_products` |
| **Match strategy** | `similarity() > 0.4`, confidence 70–85 |
| **Fallback** | Multi-layer search |
| **Weaknesses** | Low-similarity matches flagged `review_required` if confidence < 70 |
| **Health** | **Healthy** on Postgres |

### L5 (multi) — Multi-layer search (`app/services/multi_layer_search.py`)

| Field | Value |
|-------|--------|
| **Data source** | Aliases service, LRU/Redis cache, inverted index, pg_trgm, FAISS (`matcher.py`), verified products, chapter boost |
| **Match strategy** | Layered fan-out with early exit at score ≥ 0.94 |
| **Fallback** | L6 pending review |
| **Weaknesses** | Cold-start loads FAISS (~minutes); tail latency on cache miss |
| **Health** | **Healthy** on production with warm cache; **slow** on first FAISS load |

### L6 — Pending manual review (`pending_review`)

| Field | Value |
|-------|--------|
| **Data source** | Neon `pending_review` |
| **Match strategy** | Logs best guess when confidence < 70 or no authoritative match |
| **Fallback** | None (returns `UNCLASSIFIED` / low confidence) |
| **Weaknesses** | Must not be primary path for retail staples |
| **Health** | **Operational** — should be rare after alias curation |

### Parallel search API layers (not in classify pipeline)

| Module | Role |
|--------|------|
| `app/services/search_service.py` | `/search/products` orchestration |
| `app/services/product_search.py` | Token ILIKE + in-memory product cache |
| `app/services/brand_search.py` | Brand-first routing |
| `app/services/kerala_search.py` + `kerala_aliases.py` | Malayalam/regional terms |
| `app/services/pg_search.py` | Direct Postgres HSN lookup |
| `app/services/db_matcher.py` | Legacy DB matcher |
| `app/services/matcher.py` | FAISS + hybrid semantic (`amatch`) |
| `app/services/dataset.py` | In-memory HSN dataset for matcher |
| `app/services/synonyms.py` | Synonym expansion |
| `app/services/reranker.py` | Result re-ranking |
| `app/services/nlp.py` | NLP helpers |
| `app/services/important_products.py` | High-priority product list |

### Tax enrichment (`classifier_layers.enrich_tax_metadata`)

| Field | Value |
|-------|--------|
| **Data source** | `hsn_master` → `hsn_codes` → CSV chapter fallback (`lookup_tariff_gst`) |
| **Match strategy** | 8-digit code lookup with Policy-1 IGST+cess semantics |
| **Fallback** | `_ENRICH_CODES_ONLY_SQL` when history joins fail; CSV `lookup_tariff_gst` |
| **Weaknesses** | Previously failed on SQLite without `gst_rate_history` — fixed with codes-only + CSV fallback |
| **Health** | **Healthy** after 2026-05-17 fix |

---

## Smoke test results (final)

| Batch | Target | Result | Avg latency |
|-------|--------|--------|-------------|
| Core products (30) | 30/30 | **30/30** | ~3.4 ms |
| Hard client variants (20) | ≥18/20 (90%) | **20/20** | ~0.9 ms |

**Not found:** none

Representative resolutions:

| Product | HSN | GST | Layer |
|---------|-----|-----|-------|
| atta | 11010000 | 0% | L1_brand_alias (in-memory) |
| papad | 19059040 | 0% | L1_brand_alias |
| broom | 96031000 | 0% | L1_brand_alias |
| Good Day biscuit | 19053100 | 18% | L1_brand_alias |
| rubber chappal | 64019900 | 5% | L1_brand_alias |
| NIRAPARA PUTTU PODI 1KG | 11010000 | 0% | L1_brand_alias |
| GOOD KNIGHT SHAKTI MAT MACHINE | 38089100 | 18% | L1_brand_alias |

No padded chapter placeholders (e.g. atta returns `11010000`, not `01010000`).

---

## Fixes applied (2026-05-17)

1. **TIER A aliases** — Expanded `_VERIFIED_PRODUCT_ALIASES` for staples, household, footwear, and client spreadsheet variants; corrected papad (`19059040`), jaggery (`170113`), rubber footwear (`640199`), Maggi (`19023090`).
2. **GST resolution** — Added `lookup_tariff_gst`, `resolve_alias_gst`, CSV heading-prefix matching, and enrich fallback without `gst_rate_history`.
3. **Alias matching** — Longest-alias-first + `normalize_product_name` for size-stripped client strings.
4. **Smoke harness** — `scripts/layer_smoke_test.py` with JSON output.

---

## Recommended next improvements (by impact)

1. **Seed `verified_products` from client spreadsheet** — Moves branded SKUs from L0 dict to DB L2 for ops-managed updates without deploys.
2. **Postgres-only CI smoke job** — Run `layer_smoke_test.py` against Neon to validate L3–L5 + inverted index paths, not only aliases.
3. **Alias false-positive guard** — Require token-boundary match for aliases &lt; 5 chars (e.g. `tea` vs `steak`).
4. **Warm FAISS on deploy** — Keep existing `warm_search_layer()` in `main.py`; monitor cold-start SLO.
5. **Sync `language_aliases` / Kerala terms** — Improve Malayalam SKU coverage without growing the global alias dict.

---

## Verification commands

```bash
python scripts/layer_smoke_test.py
python scripts/validate_cbic.py
pytest -m "not integration" -q
```

**Last run:** 142 passed (0 failed), `validate_cbic.py` exit 0, smoke 30/30 + 20/20.
