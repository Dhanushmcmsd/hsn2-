# Accuracy Policy — HSN Classifier (Commercial B2B)

## Accuracy SLA

For **FMCG and packaged food** categories (Chapters 19–22, common brand aliases in our verified master):

| Metric | Target |
|--------|--------|
| Correct **8-digit HSN** match (top-1) | **≥ 95%** on the published FMCG benchmark set |
| Correct **GST rate** when HSN matches | **≥ 98%** |
| Confidence ≥ 70 for auto-accept | **≥ 90%** of FMCG benchmark queries |

Benchmarks are re-run before each minor release using `tests/test_brand_hsn_enrichment.py` and chapter-accuracy suites against a live Postgres mirror of production data.

## Coverage scope

**Covered (high confidence):**

- FMCG brands (health drinks, biscuits, personal care, OTC pharma keywords)
- Kerala retail invoice shorthand (VKC footwear, puja oil, spices, rice variants)
- Curated `verified_products` and `brand_aliases` tables

**Limited / not covered:**

- Industrial machinery, chemicals, and niche Chapter 84–90 goods without training aliases
- Import-specific exemptions and advance rulings
- SAC **services** (Chapter 99) — separate `service_master` path; lower coverage than goods
- Novel SKUs with no dictionary or embedding neighbour

## Update commitment

| Data asset | Refresh cadence |
|------------|-----------------|
| `data/hsn_codes.csv` (CBIC-aligned) | Within **30 days** of a CBIC GST rate notification |
| Brand / product aliases | **Bi-weekly** or on customer-reported error batch |
| Search embeddings / FAISS index | On each HSN master update |

## Error reporting (clients)

1. Email or ticket with: product query, returned HSN/GST, expected HSN/GST, invoice photo (optional).
2. We log the case in `pending_review` and target **5 business days** for data fix or classification rule update.
3. Critical misclassification (wrong GST slab > 5 percentage points) — **48-hour** hotfix when commercially supported.

Severity and response times may be defined in your **Master Service Agreement (MSA)**.
