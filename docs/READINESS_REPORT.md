# Pre-Market Sale Readiness Report

Generated: 2026-05-17

## Test results

| Check | Result | Detail |
|-------|--------|--------|
| `pytest -q` (full suite) | ✅ | 142 passed, 34 skipped, 0 failed |
| `pytest -m "not integration" -q` | ✅ | 142 passed, 0 skipped, 0 failed |
| `pytest -m integration -q` (no Neon URL) | ✅ | 34 skipped (expected without `DATABASE_URL`) |

## CBIC data integrity

| Check | Result | Detail |
|-------|--------|--------|
| `python scripts/validate_cbic.py` | ❌ | 1291 total codes; **1289** invalid format (4/6-digit rows); **30** SAC `99*` violations; 0 GST anomalies |

> Action required: normalize `data/hsn_codes.csv` to 8-digit release codes before claiming CBIC-aligned production data. CI will fail on `validate_cbic.py` until resolved.

## Required artifacts

| File | Result |
|------|--------|
| `docs/legal/DISCLAIMER.md` | ✅ |
| `docs/legal/ACCURACY_POLICY.md` | ✅ |
| `docs/legal/TERMS_OF_USE.md` | ✅ |
| `docs/cbic_validation.md` | ✅ |
| `app/services/audit_logger.py` | ✅ |
| `app/utils/request_signing.py` | ✅ |
| `.github/workflows/tests.yml` | ✅ |
| `.github/workflows/integration-tests.yml` | ✅ |

## Git history (audit trail)

```
1cafa96 fix: make test collection import-safe without DATABASE_URL
12063c4 fix: migrate ORM response models to Pydantic ConfigDict
fbe4b4c fix: resolve all 4 critical production issues (HSN codes, descriptions, GST type, API key seed)
dbcd176 chore: trigger Render redeploy — CSV +114 HSN codes + 100 product aliases + TIER A classify [2026-05-16]
fabbc7e feat: add TIER A alias pre-check — good day/papad/cumin/soup/slipper resolve instantly from verified dict
4912883 feat: add 100+ verified Indian product aliases (papad, cumin, Good Day, chappal, soup etc.) + gst_rate parsing from CSV
f3a5fec fix: expand hsn_codes.csv — add 114 missing 6-digit codes (papad, cumin, soup, footwear, biscuits) + GST rates for 219 codes
e1ae3e9 chore: trigger Render redeploy — Tier5 + hsn_search post-seed backfill [2026-05-16]
405a77d fix: run hsn_search backfill AFTER _seed_hsn_codes so search vectors are populated on fresh deploy
60da73d docs: update classify route docstring to reflect Tier 5 multi-layer fallback
```

| Check | Result |
|-------|--------|
| No loose commits (`aa`, `h1`, `check`) | ✅ |

## Integration test inventory (34 tests, `pytest -m integration`)

- `tests/test_brand_hsn_enrichment.py` — 33 tests (module-level marker)
- `tests/test_hsn_chapter_accuracy.py` — 1 test
- `tests/test_known_bad_cases.py` — 1 test
- `tests/test_kerala_search.py` — `test_kerala_search_cases_resolve_to_expected_chapters`

## Overall readiness

| Area | Status |
|------|--------|
| Unit / API tests | ✅ Ready |
| Live DB integration CI | ✅ Workflow present (`secrets.DATABASE_URL`) |
| Audit logging | ✅ Ready |
| Legal / compliance docs | ✅ Ready |
| CBIC CSV structural validation | ❌ Blocked on data normalization |
| Git audit trail | ✅ Ready |

**Recommendation:** Resolve `hsn_codes.csv` 8-digit normalization, then re-run `validate_cbic.py` and `pytest -m integration` against Neon before commercial launch.
