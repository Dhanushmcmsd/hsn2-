from __future__ import annotations
import re
import numpy as np
import structlog

log = structlog.get_logger()
_matcher_instance = None


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
        words = set(re.findall(r"\b\w{3,}\b", text.lower()))
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
            query = self._model.encode([text], normalize_embeddings=True).astype(np.float32)
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
                merged[item["hsn_code"]]["score"] = max(merged[item["hsn_code"]]["score"], item["score"])
        results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        return results[:top_k]


def get_matcher() -> HybridMatcher:
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = HybridMatcher()
    return _matcher_instance
