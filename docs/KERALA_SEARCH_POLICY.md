# Kerala / Malayalam search policy

This application is a **GST/HSN compliance classifier**, not a generic search engine.
Wrong confident matches are worse than low-confidence review cases.

The layered pipeline is intentional:

1. **preprocess** — normalize, OCR joins, roman hints (not script→roman guessing)
2. **exact / alias / verified** — preferred paths
3. **curated Kerala handling** — human-reviewed overrides
4. **controlled fuzzy** — bounded recall
5. **pending review** — uncertainty

Policy helpers live in `app/services/kerala_search_policy.py`.

---

## 1. Malayalam script is canonical

**Policy:** Queries containing Malayalam script (Unicode U+0D00–U+0D7F) are **not** roman-expanded in `preprocess_retail_query`.

**Why:**

- Guessing script→roman in preprocess is error-prone and unauditable.
- Canonical resolution belongs in **seeded `language_aliases`** (Neon/Postgres) and exact alias layers.
- Script input stays as script through preprocess; English/HSN comes from DB-backed rows.

**Do not:** add broad transliteration loops for Malayalam script in preprocess.

**Safe extension:** add `ml` rows to `data/kerala_retail_aliases.json`, rebuild, seed:

```bash
python scripts/build_kerala_retail_corpus.py
python scripts/seed_kerala_language_aliases.py
python scripts/verify_neon_seed_counts.py
```

---

## 2. Ambiguous standalone tokens are hint-only

**Policy:** Tokens such as `nadan`, `puli`, `thuvara` may appear in corpus or invoice hints but must **not** produce authoritative standalone exact HSN matches.

**Phrase-first:**

| Query | Expected behavior |
|-------|-------------------|
| `nadan ari` | Phrase expansion / alias OK |
| `thuvara parippu` | Phrase expansion OK |
| `puli inji` | Phrase expansion OK |
| `kodampuli` | Distinct product token — may expand |
| `nadan` / `puli` / `thuvara` alone | No strong translit; no exact `KERALA_ALIAS_MAP` hit |

**Mechanism:**

- Corpus rows with `priority < 50` or `notes` containing `ambiguous standalone`
- `corpus_ambiguous_standalone_tokens()` blocks standalone translit and derived alias keys
- `KERALA_ABBREVIATIONS` skips hint-only keys when query is single-token (`nadan` in curated hint set)
- `kerala_fallback_search` skips exact alias lookup via `should_block_standalone_exact_alias`

**Do not:** remove hinting entirely; do not promote standalone ambiguous tokens to high-confidence HSN.

---

## 3. Curated `CURATED_KERALA_ALIAS_MAP` overrides corpus

**Policy:** JSON corpus is the main vocabulary source. **`CURATED_KERALA_ALIAS_MAP` wins on key conflict** when merged into `KERALA_ALIAS_MAP`.

**Why:** GST filing requires a small, reviewed override layer that corpus edits alone must not silently replace.

**Inspect conflicts:**

```bash
python scripts/report_kerala_corpus_policy.py
```

**Do not:** remove curated overrides or invert merge order (`merge_alias_maps(curated, derived)`).

---

## 4. Duplicate corpus rows resolve conservatively

**Policy:** If the same single-token term appears in multiple rows and **any** row is ambiguous or low-priority, standalone exact behavior is downgraded.

**Not allowed:** “highest priority wins” for duplicates — that increases false confident matches.

**Build reporting:** `build_kerala_retail_corpus.py` prints strictly ambiguous duplicate terms after build.

---

## 5. Neon seed is explicit (never auto-seed in benchmarks)

**Policy:** Production-quality Kerala metrics require Postgres `language_aliases` rows from `KERALA_RETAIL_CORPUS`.

**Workflow:**

```bash
python scripts/build_kerala_retail_corpus.py
python scripts/seed_kerala_language_aliases.py   # explicit, idempotent
python scripts/verify_neon_seed_counts.py
python scripts/diagnose_db_environment.py
python scripts/test_client_excel.py --neon --require-kerala-corpus
```

**Benchmarks:** `--require-kerala-corpus` fails fast if DB count is below threshold. Benchmark scripts **do not** auto-seed.

**Row-count caveat (JSON vs Neon):** `data/kerala_retail_aliases.json` is the source of truth (**299** rows after `build_kerala_retail_corpus.py`). Neon `language_aliases` with `source = 'KERALA_RETAIL_CORPUS'` may read **higher** (e.g. 307–323) if older seed runs left extra active rows that no longer exist in the JSON. Preflight treats `count >= JSON - 5` as seeded; `verify_neon_seed_counts.py` compares against JSON length. For audits, trust JSON row count and upsert idempotency on `(term_normalized, language, hsn_code)` — not “DB rows == JSON rows” unless you have just re-seeded on a clean corpus.

---

## Search-layer fit

| Layer | Kerala role |
|-------|-------------|
| `preprocess_retail_query` | Roman hints only; script passthrough |
| `classify` | Stricter thresholds; skips unsafe brand early-exit for `ml` / `ml-roman` |
| `predict` / exploratory | Same preprocess; may differ in early-exit guards |
| `kerala_fallback_search` | Secondary; blocks ambiguous standalone exact alias |
| `language_aliases` (DB) | Authoritative for seeded script/roman terms |

---

## Regression tests

- `tests/test_kerala_search_policy.py` — policy contracts
- `tests/test_kerala_corpus_maps.py` — maps and phrase vs standalone
- `tests/test_kerala_retail_regression.py` — end-to-end preprocess

Run:

```bash
pytest tests/test_kerala_search_policy.py tests/test_kerala_corpus_maps.py -q
```
