# HSN Pipeline Upgrade — Change Log

Detection pipeline upgrade to raise client Excel coverage from ~26% toward 85–97% using pg_trgm, normalizer cleanup, keyword fallback, FAISS fix, and active-learning tables. No external LLM/API calls.

## Created

| File | Purpose |
|------|---------|
| `alembic/versions/0010_enable_pg_trgm_and_indexes.py` | Enable `pg_trgm`, GIN indexes on `hsn_master`, `hsn_codes`, `verified_products`, `brand_aliases`; `miss_log` table |
| `app/services/miss_logger.py` | Fire-and-forget UPSERT into `miss_log` for unclassified products (Postgres only) |
| `scripts/seed_brand_batch.py` | Infer brand→HSN via existing classify pipeline; seed `brand_aliases` + `verified_products` |

## Modified

| File | Changes |
|------|---------|
| `app/services/normalizer.py` | `expand_pos_abbreviations`, `strip_noise_tokens`, `extract_product_keywords`; wired into `normalize_product_name` |
| `app/services/pg_search.py` | `keyword_hsn_search()` — pg_trgm on `hsn_master.description` (L5 fallback) |
| `app/services/classifier_layers.py` | Curated/tariff fuzzy queries use `normalize_product_name()` |
| `app/services/gst_classifier.py` | Cleaned query path, L5 keyword fallback before tier 6, async `log_miss` |
| `app/services/multi_layer_search.py` | Keyword fallback + miss logging when no layer matches |
| `app/routes/admin.py` | `/admin/miss-log`, `/admin/pending-review`, `/admin/approve/{id}`, `/admin/bulk-approve`, clear miss log |
| `scripts/test_client_excel.py` | `--neon`, `--sample`, `--quick`, tier breakdown table, tqdm, FAISS warm once on Postgres |
| `scripts/seed_verified_from_client.py` | `--neon` flag + next-steps instructions |
| `requirements.txt` | `tqdm>=4.66.0` |
| `.github/workflows/integration-tests.yml` | `alembic upgrade head` before integration tests on Neon |
| `tests/test_classifier_layers.py` | Tests for POS expansion, noise strip, keyword extraction |

## Not modified (per spec)

- `kerala_aliases.py`, `kerala_search.py`, `hsn_master.py`, `dataset.py`, `alembic.ini`, `app/config.py`

## Deploy / validation

1. `alembic upgrade head` on Neon (enables pg_trgm + indexes)
2. `python scripts/test_client_excel.py --excel <path> --neon --quick`
3. Full run: `python scripts/test_client_excel.py --excel <path> --neon`
4. Optional seed: `python scripts/seed_brand_batch.py --report scripts/client_excel_report.json`

## Expected tier impact

| Stage | Layer | Approx. gain |
|-------|-------|----------------|
| Migration | L3 curated + L4 tariff trgm | +30–40% |
| Normalizer | Cleaner names for all layers | +10–15% |
| L5 keyword | Universal `hsn_master` fallback | +15–20% |
| Brand seeder | Frequent first-token brands | +5–8% |
| FAISS (Postgres bulk) | Semantic edge cases | +5% |
