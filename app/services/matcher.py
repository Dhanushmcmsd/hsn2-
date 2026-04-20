from __future__ import annotations
import re
import numpy as np
import structlog

log = structlog.get_logger()
_matcher_instance = None

STOPWORDS = {
    'the','a','an','and','or','of','in','is','for','to','with','on','at',
    'by','from','are','was','be','as','it','its','this','that','per','ml',
    'gm','kg','ltr','litre','liter','gram','mg','unit','pack','piece','nos',
    'no','pcs','set','box','bottle','pouch','sachet','can','tin','jar','tube',
    'strip','tablet','capsule','pkt','packet','roll','sheet','size','new','free',
    'buy','get','pure','natural','original','brand','best','premium','super',
    '100','200','250','300','400','500','1000','50','25',
    # Extended stopwords for Kerala trade invoices
    'mixed','colour','assorted','round','square','rectangular','oval','flat',
    'long','short','small','large','medium','big','tiny','huge','thick','thin',
    'wide','narrow','high','low','deep','shallow','full','empty','half','quarter',
    'whole','part','piece','slice','chunk','bit','portion','section','segment',
    'various','different','multiple','several','many','few','single','double','triple',
    'regular','extra','special','standard','basic','advanced','simple','complex',
    'normal','usual','common','rare','unique','ordinary','general','specific',
    'no1','no2','grade','quality','type','variety','model','make',
    'pkt','pouch','cover','wrapper','wt','weight','net','gross',
}

# FIX #2 & #7: VKC (footwear), CB (multi-category Kerala brand) added.
# "tr" kept OUT — abbreviation expander handles it before tokenisation.
BRANDS = {
    'patanjali','nestle','amul','tata','godrej','dettol','lifebuoy','colgate',
    'pepsodent','nivea','garnier','loreal','sony','samsung','apple',
    'lg','whirlpool','philips','nike','adidas','puma','reebok',
    'bajaj','marico','unilever','parle','sunrise','mogambo','mtr',
    'majestic','micromax','boat','mivi','britannia','honda','suzuki',
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
    'biscuit':   ['cookie'],
    'shirt':     ['tshirt'],
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
    'tr':     'kitchen treasure',  # FIX #4: Kitchen Treasure masala brand
    'ftgr':   'fenugreek',         # FIX #5: fenugreek / methi seeds
    'ss':     'stainless steel',   # FIX #6: SS PLATE, SS OVAL etc.
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
    'bluebry':'blueberry',
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
    'sug':    'sugar',
    'pick':   'pickle',
    'sach':   'sachet',
    'cann':   'canned',
    'bott':   'bottled',
    'cart':   'carton',
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
    return ' '.join(expanded)


def tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r'\b\d+\s*(ml|g|gm|kg|l|ltr|mg|oz|lb|pc|pcs|nos)\b', ' ', text)
    text = re.sub(r'\b\d+\b', ' ', text)
    tokens = re.findall(r'[a-z]{2,}', text)
    return [t for t in tokens if t not in STOPWORDS and t not in BRANDS and len(t) >= 2]


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
            import faiss
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

    def match(self, text: str, top_k: int = 5) -> list[dict]:
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


def get_matcher() -> HybridMatcher:
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = HybridMatcher()
    return _matcher_instance
