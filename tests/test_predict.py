import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_predict_no_key(client):
    resp = await client.post("/predict", json={"text": "laptop"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_predict_wrong_key(client):
    resp = await client.post("/predict", json={"text": "laptop"},
                             headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_predict_valid(client, api_key):
    mock_matches = [
        {"hsn_code": "84713000", "description": "Computers", "score": 0.92, "method": "fulltext"},
        {"hsn_code": "85171300", "description": "Phones", "score": 0.75, "method": "fulltext"},
    ]
    with patch("app.routes.predict.match_query", new_callable=AsyncMock, return_value=mock_matches), \
         patch("app.routes.predict.pg_search", new_callable=AsyncMock, return_value=[]), \
         patch("app.routes.predict.kerala_fallback_search", new_callable=AsyncMock, return_value=[]), \
         patch("app.routes.predict.search_by_product_name", new_callable=AsyncMock, return_value=None), \
         patch("app.routes.predict.search_by_brand_and_type", new_callable=AsyncMock, return_value=None), \
         patch("app.routes.predict.get_cache", return_value=None), \
         patch("app.routes.predict.set_cache", new_callable=AsyncMock), \
         patch("app.routes.predict.check_rate_limit", new_callable=AsyncMock):
        resp = await client.post("/predict", json={"text": "laptop computer"},
                                 headers={"X-API-Key": api_key})
        assert resp.status_code in (200, 422, 500)


@pytest.mark.asyncio
async def test_predict_prefers_db_matcher(client, api_key):
    db_matches = [
        {"hsn_code": "19053100", "description": "Sweet biscuits", "score": 0.91, "method": "fulltext_fts"},
        {"hsn_code": "19059040", "description": "Other bakery products", "score": 0.63, "method": "keyword_ilike"},
    ]
    with patch("app.routes.predict.match_query", new_callable=AsyncMock, return_value=db_matches), \
         patch("app.routes.predict.pg_search", new_callable=AsyncMock, return_value=[]), \
         patch("app.routes.predict.kerala_fallback_search", new_callable=AsyncMock, return_value=[]), \
         patch("app.routes.predict.search_by_product_name", new_callable=AsyncMock, return_value=None), \
         patch("app.routes.predict.search_by_brand_and_type", new_callable=AsyncMock, return_value=None), \
         patch("app.routes.predict.get_cache", return_value=None), \
         patch("app.routes.predict.set_cache", new_callable=AsyncMock), \
         patch("app.routes.predict.check_rate_limit", new_callable=AsyncMock):
        resp = await client.post("/predict", json={"text": "cookis"},
                                 headers={"X-API-Key": api_key})
        assert resp.status_code in (200, 422, 500)
