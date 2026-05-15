from __future__ import annotations
import asyncio
import re
import threading
import structlog
from collections import defaultdict
from functools import lru_cache

from app.services.kerala_aliases import (
    KERALA_ABBREVIATIONS,
    KERALA_BRAND_WORDS,
    KERALA_SYNONYMS,
)

log = structlog.get_logger()
_matcher_instance = None
_matcher_lock = threading.Lock()

STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'of', 'in', 'is', 'for', 'to', 'with', 'on', 'at',
    'by', 'from', 'are', 'was', 'be', 'as', 'it', 'its', 'this', 'that', 'per', 'ml',
    'gm', 'kg', 'ltr', 'litre', 'liter', 'gram', 'mg', 'unit', 'pack', 'piece', 'nos',
    'no', 'pcs', 'set', 'box', 'bottle', 'pouch', 'sachet', 'can', 'tin', 'jar', 'tube',
    'strip', 'tablet', 'capsule', 'pkt', 'packet', 'roll', 'sheet', 'size', 'new', 'free',
    'buy', 'get', 'pure', 'natural', 'original', 'brand', 'best', 'premium', 'super',
    '100', '200', '250', '300', '400', '500', '1000', '50', '25',
    # Extended stopwords for Kerala trade invoices
    'mixed', 'colour', 'assorted', 'round', 'square', 'rectangular', 'oval', 'flat',
    'long', 'short', 'small', 'large', 'medium', 'big', 'tiny', 'huge', 'thick', 'thin',
    'wide', 'narrow', 'high', 'low', 'deep', 'shallow', 'full', 'empty', 'half', 'quarter',
    'whole', 'part', 'piece', 'slice', 'chunk', 'bit', 'portion', 'section', 'segment',
    'various', 'different', 'multiple', 'several', 'many', 'few', 'single', 'double', 'triple',
    'regular', 'extra', 'special', 'standard', 'basic', 'advanced', 'simple', 'complex',
    'normal', 'usual', 'common', 'rare', 'unique', 'ordinary', 'general', 'specific',
    'no1', 'no2', 'grade', 'quality', 'type', 'variety', 'model', 'make',
    'cover', 'wrapper', 'wt', 'weight', 'net', 'gross',
}

# FIX #2 & #7: VKC (footwear), CB (multi-category Kerala brand) added.
# "tr" kept OUT — abbreviation expander handles it before tokenisation.
BRANDS = {
    'patanjali', 'nestle', 'amul', 'tata', 'godrej', 'dettol', 'lifebuoy', 'colgate',
    'pepsodent', 'nivea', 'garnier', 'loreal', 'sony', 'samsung', 'apple',
    'lg', 'whirlpool', 'philips', 'nike', 'adidas', 'puma', 'reebok',
    'bajaj', 'marico', 'unilever', 'parle', 'sunrise', 'mogambo', 'mtr',
    'majestic', 'micromax', 'boat', 'mivi', 'britannia', 'honda', 'suzuki',
    # Kerala-specific
    'vkc',      # VKC footwear (603 items — largest brand in dataset)
    'cb',       # CB brand — multi-category, do NOT assume any chapter
    'cbindal',
    'kitchen',  # "kitchen treasure" after TR expansion — brand word 1
    'treasure', # "kitchen treasure" after TR expansion — brand word 2
}
BRANDS.update(KERALA_BRAND_WORDS)

SYNONYMS = {
    'wash':      ['soap', 'cleanser'],
    'phone':     ['mobile', 'smartphone'],
    'tv':        ['television'],
    'fridge':    ['refrigerator'],
    'laptop':    ['notebook'],
    # FIX: shirt carries garment/clothing signal for Ch 61-63 routing
    'biscuit':   ['cookie', 'confectionery'],
    'cookie':    ['biscuit', 'confectionery'],
    'shirt':     ['tshirt', 'garment', 'clothing'],
    # FIX: water/mineral carry drink/beverage signal for Ch 22 routing
    'water':     ['beverage', 'drink'],
    'mineral':   ['beverage', 'drink'],
    'juice':     ['fruit juice', 'nectar fruit', 'beverage'],
    'aerated':   ['carbonated', 'soda', 'soft drink'],
    # FIX #3: footwear synonyms for Ch 64 routing
    'chappal':   ['sandal', 'footwear', 'slipper'],
    'slipper':   ['sandal', 'footwear', 'chappal'],
    'sandal':    ['footwear', 'slipper', 'chappal'],
    'shoe':      ['footwear'],
    'hawai':     ['slipper', 'footwear'],
    # FIX #6: stainless steel
    'stainless': ['steel', 'metal'],
    # FIX #5: fenugreek / methi
    'fenugreek': ['methi', 'spice'],
    'methi':     ['fenugreek', 'spice'],
}
SYNONYMS.update(KERALA_SYNONYMS)

# FIX #1–#6: Expanded abbreviation table
FMCG_ABBREVIATIONS = {
    # v2.2.0 additions
    'tr':     'kitchen treasure',   # FIX #4: Kitchen Treasure masala brand prefix
    'ftgr':   'fenugreek',          # FIX #5: fenugreek / methi seeds
    'ss':     'stainless steel',    # FIX #6: SS PLATE, SS OVAL etc.
    'ss.':    'stainless steel',
    # Cleaning
    'btrm':   'bathroom',
    'bathrm': 'bathroom',
    'bthrm':  'bathroom',
    'clnr':   'cleaner',
    'toilt':  'toilet',
    'tolt':   'toilet',
    'tlt':    'toilet',
    'disinft': 'disinfectant',
    'disinftnt': 'disinfectant',
    'dtgnt':  'detergent',
    # Food
    'cookis': 'cookie',
    'cashw':  'cashew',
    'jasmne': 'jasmine',
    'choc':   'chocolate',
    'van':    'vanilla',
    'strbry': 'strawberry',
    'rasbry': 'raspberry',
    'bluebry': 'blueberry',
    'blkbry': 'blackberry',
    'pstr':   'pasta',
    'nood':   'noodle',
    'sauc':   'sauce',
    'ketch':  'ketchup',
    'must':   'mustard',
    'mayo':   'mayonnaise',
    'yog':    'yogurt',
    'chee':   'cheese',
    'butr':   'butter',
    'marg':   'margarine',
    # Personal care
    'shamp':  'shampoo',
    'cond':   'conditioner',
    'det':    'detergent',
    'fab':    'fabric',
    'soft':   'softener',
    'dish':   'dishwasher',
    'liq':    'liquid',
    'powd':   'powder',
    'powdr':  'powder',
    'pwdr':   'powder',
    'pdr':    'powder',
    'tab':    'tablet',
    'cap':    'capsule',
    'syrup':  'syrup',
    # Condiments
    'vin':    'vinegar',
    'jam':    'jam',
    'jelly':  'jelly',
    'marm':   'marmalade',
    'pick':   'pickle',
    'spice':  'spice',
    'herb':   'herb',
    'sug':    'sugar',
    # Packaging descriptors
    'cann':   'canned',
    'bott':   'bottled',
    'cart':   'carton',
    'sach':   'sachet',
    # Trade
    'prem':   'premium',
    'org':    'organic',
    'nat':    'natural',
    'imp':    'imported',
    'loc':    'local',
    'dom':    'domestic',
    'froz':   'frozen',
}
FMCG_ABBREVIATIONS.update(KERALA_ABBREVIATIONS)


def expand_fmcg_abbreviations(text: str) -> str:
    """
    Expand FMCG / trade abbreviations.
    Pattern-based rules run first (handles word-boundary cases),
    then token-by-token dictionary lookup.
    """
    # FIX #6: SS prefix → stainless steel
    text = re.sub(r'\bSS\b', 'stainless steel', text, flags=re.IGNORECASE)
    # FIX #5: FTGR → fenugreek
    text = re.sub(r'\bFTGR\b', 'fenugreek', text, flags=re.IGNORECASE)
    # FIX #4: TR. or TR (word boundary) → kitchen treasure
    text = re.sub(r'\bTR\.\s*', 'kitchen treasure ', text, flags=re.IGNORECASE)
    text = re.sub(r'\bTR\b', 'kitchen treasure', text, flags=re.IGNORECASE)

    words = text.split()
    expanded = []
    for word in words:
        lower = word.lower().rstrip('.')
        expanded.append(FMCG_ABBREVIATIONS.get(lower, word))
    deduped: list[str] = []
    for word in expanded:
        if deduped and deduped[-1].lower() == str(word).lower():
            continue
        deduped.append(word)
    return ' '.join(deduped).lower()


def tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r'\b\d+\s*(ml|g|gm|kg|l|ltr|mg|oz|lb|pc|pcs|nos)\b', ' ', text)
    text = re.sub(r'\b\d+\b', ' ', text)
    tokens = re.findall(r'[a-z]{2,}', text)
    return [t for t in tokens if t not in STOPWORDS and t not in BRANDS and len(t) >= 2]


def strip_sizes(text: str) -> str:
    """Normalize text for size-insensitive verified-product lookups."""
    text = re.sub(
        r'\b\d+(?:\.\d+)?\s*(?:g|gm|gms|kg|kgs|ml|l|ltr|litre|liter|'
        r'pc|pcs|nos|no|n|p|in|mg|oz|lb)\b',
        ' ',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r'\b\d+\s*x\s*\d+\b', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d+\s*\+\s*\d+\b', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d+[snp]\b', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d+\b', ' ', text)
    text = re.sub(r'[^A-Za-z\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip().upper()


def _normalize_for_match(text: str) -> str:
    text = expand_fmcg_abbreviations(text).upper()
    text = re.sub(r'[^A-Z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _extract_pack_size(text: str) -> tuple[float, str] | None:
    match = re.search(r'\b(\d+(?:\.\d+)?)\s*(ML|L|LTR|G|GM|KG)\b', text.upper())
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit in {'L', 'LTR'}:
        value *= 1000
        unit = 'ML'
    if unit == 'KG':
        value *= 1000
        unit = 'G'
    if unit == 'GM':
        unit = 'G'
    return value, unit


def _size_similarity(query_text: str, item_text: str) -> float:
    query_size = _extract_pack_size(query_text)
    item_size = _extract_pack_size(item_text)
    if not query_size or not item_size:
        return 0.0
    if query_size[1] != item_size[1]:
        return 0.0
    diff = abs(query_size[0] - item_size[0])
    if diff == 0:
        return 0.14
    largest = max(query_size[0], item_size[0], 1)
    closeness = 1 - min(diff / largest, 1.0)
    return round(closeness * 0.08, 4)


def _query_intent_adjustment(normalized_query: str, item_tokens: set[str]) -> float:
    adjustment = 0.0
    if normalized_query == "HARPIC":
        if {"toilet", "cleaner", "bathroom", "disinfectant"} & item_tokens:
            adjustment += 0.12
        if {"flushmatic", "rim", "block"} & item_tokens:
            adjustment -= 0.08
    if normalized_query == "SESAME":
        if {"oil", "gingelly"} & item_tokens:
            adjustment += 0.08
        if {"ball", "candy", "chikky"} & item_tokens:
            adjustment -= 0.04
    if "JUICE" in normalized_query:
        if {"fruit", "beverage", "drink", "orange", "mango", "apple"} & item_tokens:
            adjustment += 0.12
        if {"hair", "shampoo", "cleanser", "cleansing", "cream", "cosmetic"} & item_tokens:
            adjustment -= 0.18
    if "FRUIT JAM" in normalized_query and "mixed" in item_tokens:
        adjustment += 0.06
    return adjustment


@lru_cache(maxsize=1)
def _load_spacy_model():
    """Best-effort spaCy loader; returns None when spaCy/model is unavailable."""
    try:
        import spacy
        return spacy.load("en_core_web_sm")
    except Exception as exc:
        log.info("matcher.spacy_unavailable", error=str(exc))
        return None


def extract_core_product(text: str) -> str:
    """
    Extract the most product-like term from the query.

    Preferred path uses spaCy to capture the last noun/proper noun.
    Fallback path uses the last meaningful token after abbreviation expansion.
    """
    expanded = expand_fmcg_abbreviations(text)
    nlp = _load_spacy_model()
    if nlp is not None:
        try:
            doc = nlp(expanded)
            nouns = [
                token.lemma_.lower()
                for token in doc
                if token.pos_ in {"NOUN", "PROPN"}
                and token.is_alpha
                and token.lemma_.lower() not in STOPWORDS
                and token.lemma_.lower() not in BRANDS
            ]
            if nouns:
                return nouns[-1]
        except Exception as exc:
            log.warning("matcher.spacy_extract_failed", error=str(exc))

    fallback_tokens = re.findall(r'[a-z]{2,}', expanded.lower())
    meaningful = [
        token for token in fallback_tokens
        if token not in STOPWORDS and token not in BRANDS
    ]
    return meaningful[-1] if meaningful else ""


def expand_tokens(tokens: list[str]) -> list[str]:
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        expanded.extend(SYNONYMS.get(token, []))
    return expanded


class HybridMatcher:
    def __init__(self):
        self._dataset: list[dict] = []
        self._exact_map: dict[str, list[dict]] = {}
        self._no_size_map: dict[str, list[dict]] = {}
        self._fuzz_descriptions: list[str] = []
        self._load()

    @property
    def ready(self) -> bool:
        return True

    def _load(self):
        from app.services.dataset import get_dataset
        log.info("matcher.load_start", phase="dataset")
        self._dataset = get_dataset()
        if not self._dataset:
            log.warning("matcher.empty_dataset")
            return
        log.info("matcher.load_progress", phase="indices", row_count=len(self._dataset))
        self._exact_map = defaultdict(list)
        self._no_size_map = defaultdict(list)
        self._fuzz_descriptions = [d["description"] for d in self._dataset]
        for row in self._dataset:
            self._exact_map[row["description_normalized"]].append(row)
            expanded_norm = _normalize_for_match(row["description"])
            if expanded_norm != row["description_normalized"]:
                self._exact_map[expanded_norm].append(row)
            if row.get("description_no_size"):
                self._no_size_map[row["description_no_size"]].append(row)
            expanded_no_size = strip_sizes(expand_fmcg_abbreviations(row["description"]))
            if expanded_no_size and expanded_no_size != row.get("description_no_size"):
                self._no_size_map[expanded_no_size].append(row)

    def _exact_code_match(self, text: str) -> list[dict]:
        text_lower = text.lower()
        results = []
        for item in self._dataset:
            if item["hsn_code"].lower() == text_lower:
                results.append({**item, "score": 1.0, "method": "exact_code"})
        return results

    def _source_bonus(self, item: dict) -> float:
        return {
            "correct_datas": 0.18,
            "product_batch": 0.14,
            "hsn_codes": 0.04,
        }.get(item.get("source", ""), 0.0)

    def _rank_grouped_matches(self, matches: list[dict], top_k: int) -> list[dict]:
        grouped: dict[str, dict] = {}
        support_counts = defaultdict(int)
        score_sums = defaultdict(float)
        for item in matches:
            key = item["hsn_code"]
            support_counts[key] += 1
            score_sums[key] += item["score"]
            current = grouped.get(key)
            current_key = (
                current["score"],
                current.get("_size_bonus", 0.0),
                current.get("_coverage", 0.0),
                -len(current["description"]),
            ) if current else None
            item_key = (
                item["score"],
                item.get("_size_bonus", 0.0),
                item.get("_coverage", 0.0),
                -len(item["description"]),
            )
            if not current or item_key > current_key:
                grouped[key] = dict(item)

        ranked = []
        for key, item in grouped.items():
            enriched = dict(item)
            enriched["_support_count"] = support_counts[key]
            enriched["_average_score"] = round(score_sums[key] / support_counts[key], 4)
            ranked.append(enriched)

        ranked.sort(
            key=lambda item: (
                item["score"],
                item["_support_count"],
                item["_average_score"],
                item.get("_size_bonus", 0.0),
                item.get("_coverage", 0.0),
                -len(item["description"]),
            ),
            reverse=True,
        )

        trimmed = []
        for item in ranked[:top_k]:
            cleaned = dict(item)
            cleaned.pop("_support_count", None)
            cleaned.pop("_average_score", None)
            cleaned.pop("_size_bonus", None)
            cleaned.pop("_coverage", None)
            trimmed.append(cleaned)
        return trimmed

    def _exact_description_match(self, text: str, top_k: int) -> list[dict]:
        normalized = strip_sizes(text)
        exact_rows = list(self._exact_map.get(_normalize_for_match(text), []))
        if exact_rows:
            matches = []
            for row in exact_rows:
                matches.append({
                    **row,
                    "score": round(min(1.0, 0.82 + self._source_bonus(row)), 4),
                    "method": f"{row['source']}_exact",
                })
            return self._rank_grouped_matches(matches, top_k)

        no_size_rows = list(self._no_size_map.get(normalized, []))
        if no_size_rows:
            matches = []
            for row in no_size_rows:
                matches.append({
                    **row,
                    "score": round(min(0.99, 0.76 + self._source_bonus(row)), 4),
                    "method": f"{row['source']}_no_size",
                })
            return self._rank_grouped_matches(matches, top_k)

        return []

    def _token_score(self, query_tokens: list[str], item_tokens: set[str], source: str, core_product: str) -> float:
        if not query_tokens or not item_tokens:
            return 0.0
        overlap = len(set(query_tokens) & item_tokens)
        if overlap == 0:
            return 0.0
        coverage = overlap / max(len(set(query_tokens)), 1)
        precision = overlap / max(len(item_tokens), 1)
        score = (coverage * 0.68) + (precision * 0.20)
        if core_product and core_product in item_tokens:
            score += 0.10
        score += self._source_bonus({"source": source})
        return min(score, 0.94)

    def _phrase_match(self, text: str, top_k: int) -> list[dict]:
        normalized = _normalize_for_match(text)
        no_size = strip_sizes(text)
        query_tokens = tokenize(expand_fmcg_abbreviations(text))
        expanded_tokens = expand_tokens(query_tokens)
        core_product = extract_core_product(text)
        query_token_set = set(expanded_tokens)
        scored: list[dict] = []

        for item in self._dataset:
            desc_norm = _normalize_for_match(item["description"])
            desc_no_size = strip_sizes(expand_fmcg_abbreviations(item["description"]))
            item_tokens = set(tokenize(expand_fmcg_abbreviations(item["description"])))
            overlap = len(query_token_set & item_tokens)
            coverage = overlap / max(len(query_token_set), 1) if query_token_set else 0.0
            size_bonus = _size_similarity(text, item["description"])
            intent_adjustment = _query_intent_adjustment(normalized, item_tokens)

            score = self._token_score(expanded_tokens, item_tokens, item.get("source", ""), core_product)
            score = max(0.0, min(1.0, score + intent_adjustment))
            method = "token"

            if normalized and normalized == desc_norm:
                score = max(score, min(1.0, 0.84 + self._source_bonus(item) + size_bonus + intent_adjustment))
                method = "exact_phrase"
            elif no_size and no_size == desc_no_size:
                score = max(score, min(0.98, 0.78 + self._source_bonus(item) + size_bonus + intent_adjustment))
                method = "no_size_phrase"
            elif normalized and normalized in desc_norm:
                phrase_score = 0.56 + (coverage * 0.18) + self._source_bonus(item) + size_bonus + intent_adjustment
                score = max(score, min(0.94, phrase_score))
                method = "contains_phrase"
            elif no_size and no_size and no_size in desc_no_size:
                phrase_score = 0.54 + (coverage * 0.16) + self._source_bonus(item) + size_bonus + intent_adjustment
                score = max(score, min(0.92, phrase_score))
                method = "contains_no_size"
            elif core_product and core_product in item_tokens:
                method = "core_product"

            if score <= 0.0:
                continue

            scored.append({
                **item,
                "score": round(score, 4),
                "method": f"{item['source']}_{method}",
                "_size_bonus": size_bonus,
                "_coverage": round(coverage, 4),
            })

        return self._rank_grouped_matches(scored, top_k)

    def _keyword_match(self, text: str, top_k: int) -> list[dict]:
        return self._phrase_match(text, top_k)

    def _semantic_match(self, text: str, top_k: int) -> list[dict]:
        return []

    def _match_once(self, text: str, top_k: int = 5) -> list[dict]:
        exact_code = self._exact_code_match(text)
        if exact_code:
            return exact_code[:top_k]

        exact_desc = self._exact_description_match(text, top_k)
        if exact_desc:
            return exact_desc[:top_k]

        semantic = self._semantic_match(text, top_k * 2)
        keyword = self._keyword_match(text, top_k * 2)
        merged: dict[str, dict] = {}
        for item in keyword:
            merged[item["hsn_code"]] = item
        for item in semantic:
            existing = merged.get(item["hsn_code"])
            if not existing:
                merged[item["hsn_code"]] = dict(item)
                continue
            semantic_score = round(item["score"] * 0.9, 4)
            if semantic_score > existing["score"]:
                merged[item["hsn_code"]] = {
                    **item,
                    "score": semantic_score,
                    "method": f"{item['method']}_blended",
                }
        results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)

        if len(results) > 1:
            try:
                from app.services.nlp import extract_entities
                from app.services.reranker import get_reranker

                reranker = get_reranker()
                entities = extract_entities(text)
                return reranker.rerank(
                    text,
                    results[: top_k * 2],
                    top_k=top_k,
                    query_entities=entities,
                )
            except Exception as exc:
                log.warning("reranker.failed", error=str(exc))

        return results[:top_k]

    def _should_retry_with_core_product(self, text: str, matches: list[dict]) -> bool:
        if not text.strip():
            return False
        if not matches:
            return True
        return matches[0].get("score", 0.0) < 0.35

    def _tag_retry_matches(self, matches: list[dict], core_product: str) -> list[dict]:
        tagged = []
        for item in matches:
            updated = dict(item)
            method = updated.get("method", "unknown")
            updated["method"] = f"{method}_last_noun_retry"
            updated["retry_query"] = core_product
            tagged.append(updated)
        return tagged

    def match(self, text: str, top_k: int = 5) -> list[dict]:
        primary_results = self._match_once(text, top_k=top_k)
        if not self._should_retry_with_core_product(text, primary_results):
            return primary_results

        core_product = extract_core_product(text)
        normalized_text = expand_fmcg_abbreviations(text).strip().lower()
        if not core_product or core_product == normalized_text:
            return primary_results

        retry_results = self._match_once(core_product, top_k=top_k)
        if not retry_results:
            return primary_results

        if not primary_results or retry_results[0].get("score", 0.0) > primary_results[0].get("score", 0.0):
            log.info(
                "matcher.last_noun_retry_used",
                original_text=text[:80],
                retry_query=core_product,
                original_score=primary_results[0].get("score", 0.0) if primary_results else 0.0,
                retry_score=retry_results[0].get("score", 0.0),
            )
            return self._tag_retry_matches(retry_results, core_product)

        return primary_results

    async def amatch(self, text: str, top_k: int = 5) -> list[dict]:
        """Run :meth:`match` in a worker thread so FAISS / embedding work does not block the event loop."""
        return await asyncio.to_thread(self.match, text, top_k)


def get_matcher() -> HybridMatcher:
    global _matcher_instance
    if _matcher_instance is None:
        with _matcher_lock:
            if _matcher_instance is None:
                _matcher_instance = HybridMatcher()
    return _matcher_instance
