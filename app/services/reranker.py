from __future__ import annotations

import re
from functools import lru_cache

import structlog

log = structlog.get_logger()


class LightweightReranker:
    """
    Feature-based reranker for HSN candidates.

    The current implementation uses handcrafted features and a weighted
    combination so it stays fast enough for request-time reranking.
    """

    def score(
        self,
        query: str,
        candidate: dict,
        embedding_score: float,
        *,
        query_entities=None,
    ) -> float:
        features = self._extract_features(
            query, candidate, embedding_score, query_entities=query_entities
        )
        return self._combine_features(features)

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        *,
        top_k: int = 5,
        query_entities=None,
        method_suffix: str = "reranked",
    ) -> list[dict]:
        if len(candidates) <= 1:
            return candidates[:top_k]

        rescored: list[dict] = []
        for index, candidate in enumerate(candidates):
            updated = dict(candidate)
            base_score = self._safe_float(
                updated.get("score", updated.get("confidence", 0.0))
            )
            reranked_score = round(
                self.score(
                    query,
                    updated,
                    embedding_score=base_score,
                    query_entities=query_entities,
                ),
                4,
            )
            updated["score"] = reranked_score
            if "confidence" in updated:
                updated["confidence"] = reranked_score
            method = str(updated.get("method", "")).strip()
            if method and not method.endswith(f"_{method_suffix}"):
                updated["method"] = f"{method}_{method_suffix}"
            updated["_rerank_index"] = index
            rescored.append(updated)

        rescored.sort(
            key=lambda item: (item["score"], -item["_rerank_index"]),
            reverse=True,
        )
        for item in rescored:
            item.pop("_rerank_index", None)
        return rescored[:top_k]

    def _extract_features(
        self,
        query: str,
        candidate: dict,
        embedding_score: float,
        *,
        query_entities=None,
    ) -> dict:
        try:
            from app.services.matcher import expand_fmcg_abbreviations

            query_text = expand_fmcg_abbreviations(query)
            desc_text = expand_fmcg_abbreviations(candidate.get("description", ""))
        except Exception:
            query_text = str(query or "")
            desc_text = str(candidate.get("description", "") or "")

        q_upper = query_text.upper()
        desc_upper = desc_text.upper()
        hsn_code = str(candidate.get("hsn_code", ""))

        q_tokens = set(re.findall(r"[A-Z]{3,}", q_upper))
        d_tokens = set(re.findall(r"[A-Z]{3,}", desc_upper))

        intersection = q_tokens & d_tokens
        union = q_tokens | d_tokens

        return {
            "embedding_score": self._safe_float(embedding_score),
            "token_jaccard": len(intersection) / max(len(union), 1),
            "query_coverage": len(intersection) / max(len(q_tokens), 1),
            "desc_precision": len(intersection) / max(len(d_tokens), 1),
            "length_ratio": min(len(q_upper), len(desc_upper))
            / max(len(q_upper), len(desc_upper), 1),
            "chapter_match": self._chapter_match_score(hsn_code, query_entities),
            "source_priority": self._source_priority_score(candidate),
            "prior_confidence": self._safe_float(
                candidate.get("confidence", candidate.get("score", 0.0))
            ),
            "desc_specificity": min(len(desc_upper) / 100.0, 1.0),
            "brand_match": self._brand_match_score(
                q_upper, desc_upper, query_entities
            ),
        }

    def _chapter_match_score(self, hsn_code: str, entities) -> float:
        if entities is None:
            return 0.5
        chapter_hints = getattr(entities, "chapter_hint", [])
        if not chapter_hints:
            return 0.5
        code_digits = re.sub(r"[^0-9]", "", hsn_code)
        if any(code_digits.startswith(chapter) for chapter in chapter_hints):
            return 1.0
        return 0.0

    def _brand_match_score(self, q_upper: str, desc_upper: str, entities) -> float:
        if entities is None:
            return 0.5
        brand = getattr(entities, "brand", None)
        if not brand:
            return 0.5
        brand_upper = str(brand).upper()
        q_has_brand = brand_upper in q_upper
        d_has_brand = brand_upper in desc_upper
        if q_has_brand and d_has_brand:
            return 1.0
        if q_has_brand and not d_has_brand:
            return 0.2
        return 0.5

    def _source_priority_score(self, candidate: dict) -> float:
        source = self._candidate_source(candidate)
        return {
            "verified_exact": 1.0,
            "correct_datas": 0.9,
            "product_batch": 0.8,
            "hsn_codes": 0.5,
        }.get(source, 0.5)

    def _candidate_source(self, candidate: dict) -> str:
        source = str(candidate.get("source", "")).strip().lower()
        if source:
            if source.startswith("verified"):
                return "verified_exact"
            return source

        method = str(
            candidate.get("method", candidate.get("match_method", ""))
        ).strip().lower()
        if method.startswith("verified"):
            return "verified_exact"
        if method.startswith("correct_datas"):
            return "correct_datas"
        if method.startswith("product_batch"):
            return "product_batch"
        if method.startswith("hsn_codes"):
            return "hsn_codes"
        return "hsn_codes"

    def _combine_features(self, features: dict) -> float:
        score = (
            features["embedding_score"] * 0.30
            + features["token_jaccard"] * 0.20
            + features["query_coverage"] * 0.15
            + features["desc_precision"] * 0.05
            + features["length_ratio"] * 0.02
            + features["chapter_match"] * 0.10
            + features["source_priority"] * 0.05
            + features["prior_confidence"] * 0.08
            + features["desc_specificity"] * 0.03
            + features["brand_match"] * 0.02
        )
        return max(0.0, min(1.0, score))

    def _safe_float(self, value: object) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0


@lru_cache(maxsize=1)
def get_reranker() -> LightweightReranker:
    return LightweightReranker()
