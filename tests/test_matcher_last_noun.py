from app.services.matcher import extract_core_product, HybridMatcher


def test_extract_core_product_falls_back_to_last_meaningful_token():
    assert extract_core_product("Kitchen Treasure turmeric powder 500g") == "powder"


def test_match_retries_with_core_product_when_primary_search_fails():
    matcher = HybridMatcher.__new__(HybridMatcher)

    calls: list[str] = []

    def fake_match_once(text: str, top_k: int = 5):
        calls.append(text)
        if text == "Kitchen Treasure turmeric powder 500g":
            return []
        if text == "powder":
            return [
                {
                    "hsn_code": "09103000",
                    "description": "Turmeric powder",
                    "score": 0.61,
                    "method": "keyword",
                }
            ]
        return []

    matcher._match_once = fake_match_once

    results = matcher.match("Kitchen Treasure turmeric powder 500g")

    assert calls == ["Kitchen Treasure turmeric powder 500g", "powder"]
    assert results[0]["hsn_code"] == "09103000"
    assert results[0]["method"] == "keyword_last_noun_retry"
    assert results[0]["retry_query"] == "powder"
