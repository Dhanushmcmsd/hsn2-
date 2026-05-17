# Kerala invoice benchmark — before/after

**Date:** 2026-05-18  
**Sample:** `data/kerala_invoice_benchmark.xlsx` — **91** lines (roman invoice OCR + Malayalam script), not generic FMCG  
**Environment:** Neon Postgres, `--skip-faiss` (FAISS warm-up did not complete within timeout)

## Seed

- JSON corpus: **299** rows  
- Neon `KERALA_RETAIL_CORPUS`: **299** active after final seed (upsert idempotent)  
- Preflight `--require-kerala-corpus`: **pass**

## Results (no FAISS)

| Metric | Before (DB corpus off) | After (DB seeded) | Generic FMCG (200 rows) |
|--------|------------------------|-------------------|------------------------|
| Detection rate | 29.7% (27/91) | 29.7% (27/91) | 55.0% (110/200) |
| Kerala-style lines | 52 | 52 | 6 |
| Kerala detected | 13 | 13 | 2 |
| `kerala_exact_or_alias_hits` | 5 | 5 | 0 |
| `L0_kerala_retail` (all rows) | 24 | 24 | 0 |
| `language_aliases` tier | 0 | 0 | 0 |

**FAISS:** Not reported — matcher warm-up exceeded 5 minutes; use `--skip-faiss` for Kerala layer testing until FAISS load is fixed.

## Interpretation

- **Dataset matters:** Kerala invoice sample surfaces **24** `L0_kerala_retail` hits vs **0** on the generic catalog slice.  
- **Neon seed:** Required for production (`language_aliases`, script queries, preflight). This roman-heavy run is dominated by in-memory `L0_kerala` + JSON maps, so DB on/off did not change headline metrics.  
- **Remaining gap:** ~70% of lines still fail strict detection (often HSN present but `gst_rate`/confidence gates); Malayalam script lines mostly land in `L6_pending_review` — DB seed alone does not fix FTS/script ranking without further search tuning.

## Artifacts

- `scripts/kerala_benchmark_matrix/before_seed_no_faiss.json`  
- `scripts/kerala_benchmark_matrix/after_seed_no_faiss.json`  
- `scripts/kerala_benchmark_matrix/matrix_summary.json`
