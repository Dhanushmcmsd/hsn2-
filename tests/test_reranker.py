from app.services.nlp import extract_entities
from app.services.reranker import get_reranker


def test_reranker_prefers_brand_and_product_alignment_for_raw_query():
    reranker = get_reranker()
    query = "VKC CHAPPAL SIZE 7"
    entities = extract_entities(query)

    good_candidate = {
        "hsn_code": "64029990",
        "description": "VKC rubber slipper for adults",
        "source": "product_batch",
        "score": 0.62,
        "confidence": 0.62,
        "method": "semantic",
    }
    weaker_candidate = {
        "hsn_code": "39249090",
        "description": "plastic household basket",
        "source": "hsn_codes",
        "score": 0.62,
        "confidence": 0.62,
        "method": "semantic",
    }

    good_score = reranker.score(query, good_candidate, 0.62, query_entities=entities)
    weak_score = reranker.score(query, weaker_candidate, 0.62, query_entities=entities)

    assert good_score > weak_score


def test_reranker_handles_uncleaned_abbreviation_queries():
    reranker = get_reranker()
    query = "HARPIC BTRM CLNR 500ML"
    entities = extract_entities(query)

    candidates = [
        {
            "hsn_code": "34022090",
            "description": "Harpic bathroom cleaner liquid",
            "source": "product_batch",
            "score": 0.58,
            "confidence": 0.58,
            "method": "keyword",
        },
        {
            "hsn_code": "34029011",
            "description": "floor disinfectant liquid cleaner",
            "source": "hsn_codes",
            "score": 0.61,
            "confidence": 0.61,
            "method": "keyword",
        },
    ]

    reranked = reranker.rerank(
        query,
        candidates,
        top_k=2,
        query_entities=entities,
    )

    assert reranked[0]["hsn_code"] == "34022090"
    assert reranked[0]["method"].endswith("_reranked")
