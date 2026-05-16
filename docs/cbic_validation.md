# CBIC HSN Alignment Validation

## Source

HSN codes in this system are sourced from the **CBIC Customs Tariff Act, 1975** and the **GST HSN master** published at [cbic.gov.in](https://www.cbic.gov.in/). The canonical local file is `data/hsn_codes.csv`.

## Validation method

Before every release:

1. Download or obtain the current official CBIC GST HSN master (chapter headings, sub-headings, and 8-digit tariff lines).
2. Run `python scripts/validate_cbic.py` locally and in CI (`.github/workflows/tests.yml`).
3. Cross-verify every 8-digit code in `data/hsn_codes.csv` against the CBIC master:
   - Code must exist in the official tariff.
   - Description should match or be a faithful abbreviation of the CBIC line.
   - `gst_rate` must match the notified GST slab for that code.
4. Record the CBIC master version/date in the release notes (see Version tracking).

Structural checks enforced automatically:

- All codes are exactly **8 digits** (no 4- or 6-digit rows in the release file).
- Codes starting with **99** must be valid **SAC** service codes (8-digit, `99xxxxxx`).
- `gst_rate` must be one of: `0`, `0.1`, `0.25`, `1.5`, `3`, `5`, `12`, `18`, `28`.

## Discrepancy process

1. **Report**: Open a GitHub issue labelled `data/cbic` with the HSN code, expected CBIC value, and source notification/date.
2. **Triage**: Maintainer confirms against the official CBIC PDF/portal export.
3. **Correct**: Update `data/hsn_codes.csv`, re-run `scripts/validate_cbic.py`, and add a row to the release changelog.
4. **Verify**: CI must pass; integration tests on Neon should be run before tagging a release.

## Version tracking

Each release tag or `CHANGELOG` entry must include:

- **CBIC master version/date** validated against (e.g. `CBIC GST HSN master as of 2026-04-01`).
- **Commit SHA** of `data/hsn_codes.csv` included in that release.
- Result of `scripts/validate_cbic.py` (pass/fail and code count).

Example:

```
Release 2.3.1 — validated against CBIC GST HSN master 2026-04-01; 1,291 codes; validate_cbic.py PASS.
```
