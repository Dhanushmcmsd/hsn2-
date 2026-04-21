from __future__ import annotations
import re
import numpy as np
import structlog
from functools import lru_cache

log = structlog.get_logger()
_matcher_instance = None

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

# FIX #1–#6: Expanded abbreviation table
FMCG_ABBREVIATIONS = {
    # v2.2.0 additions
    'tr':     'kitchen treasure',   # FIX #4: Kitchen Treasure masala brand prefix
    'ftgr':   'fenugreek',          # FIX #5: fenugreek / methi seeds
    'ss':     'stainless steel',    # FIX #6: SS PLATE, SS OVAL etc.
    'ss.':    'stainless steel',
    # Cleaning
    'btrm':   'bathroom',
    'clnr':   'cleaner',
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
    return ' '.join(expanded).lower()


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
        self._embeddings = None
        self._model = None
        self._ready = False
        self._load()

    def _load(self):
        from app.services.dataset import get_dataset
        from app.config import settings
        self._dataset = get_dataset()
        if not self._dataset:
            log.warning("matcher.empty_dataset")
            return
        try:
            from sentence_transformers import SentenceTransformer
            import faiss
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
            texts = [d["description"] for d in self._dataset]
            self._embeddings = self._model.encode(texts, normalize_embeddings=True)
            dim = self._embeddings.shape[1]
            self._index = faiss.IndexFlatIP(dim)
            self._index.add(self._embeddings.astype(np.float32))
            self._ready = True
            log.info("matcher.ready", count=len(self._dataset))
        except Exception as e:
            log.warning("matcher.load_error", error=str(e))

    def _exact_match(self, text: str) -> list[dict]:
        text_lower = text.lower()
        results = []
        for item in self._dataset:
            if item["hsn_code"].lower() == text_lower:
                results.append({**item, "score": 1.0, "method": "exact_code"})
        return results

    def _keyword_match(self, text: str, top_k: int) -> list[dict]:
        # Expand abbreviations before tokenising
        text = expand_fmcg_abbreviations(text)
        tokens = tokenize(text)
        if not tokens:
            return []
        words = set(expand_tokens(tokens))
        scored = []
        for item in self._dataset:
            desc_words = set(re.findall(r"\b\w{3,}\b", item["description"].lower()))
            if not desc_words:
                continue
            overlap = len(words & desc_words) / max(len(words), 1)
            if overlap > 0:
                scored.append({**item, "score": round(overlap * 0.75, 4), "method": "keyword"})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def _semantic_match(self, text: str, top_k: int) -> list[dict]:
        if not self._ready:
            return []
        try:
            import faiss  # noqa: F401
            # Expand abbreviations before encoding
            text = expand_fmcg_abbreviations(text)
            tokens = tokenize(text)
            query_text = " ".join(expand_tokens(tokens)) if tokens else text.lower()
            query = self._model.encode([query_text], normalize_embeddings=True).astype(np.float32)
            scores, indices = self._index.search(query, top_k)
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0:
                    continue
                item = self._dataset[idx]
                results.append({**item, "score": round(float(score), 4), "method": "semantic"})
            return results
        except Exception as e:
            log.warning("matcher.semantic_error", error=str(e))
            return []

    def _match_once(self, text: str, top_k: int = 5) -> list[dict]:
        exact = self._exact_match(text)
        if exact:
            return exact[:top_k]
        semantic = self._semantic_match(text, top_k * 2)
        keyword = self._keyword_match(text, top_k * 2)
        merged: dict[str, dict] = {}
        for item in semantic:
            merged[item["hsn_code"]] = item
        for item in keyword:
            if item["hsn_code"] not in merged:
                merged[item["hsn_code"]] = item
            else:
                merged[item["hsn_code"]]["score"] = max(
                    merged[item["hsn_code"]]["score"], item["score"]
                )
        results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
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


def get_matcher() -> HybridMatcher:
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = HybridMatcher()
    return _matcher_instance
