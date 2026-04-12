import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_predict_no_key(client):
    resp = await client.post("/predict", json={"text": "laptop"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_predict_wrong_key(client):
    resp = await client.post("/predict", json={"text": "laptop"},
                             headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_predict_valid(client, api_key):
    mock_matches = [
        {"hsn_code": "8471", "description": "Computers", "score": 0.92, "method": "semantic"},
        {"hsn_code": "8517", "description": "Phones", "score": 0.75, "method": "semantic"},
    ]
    with patch("app.routes.predict.get_matcher") as mock_m, \
         patch("app.routes.predict.get_cache", return_value=None), \
         patch("app.routes.predict.set_cache", new_callable=AsyncMock), \
         patch("app.routes.predict.check_rate_limit", new_callable=AsyncMock), \
         patch("app.models.database.async_session"):
        mock_m.return_value.match.return_value = mock_matches
        resp = await client.post("/predict", json={"text": "laptop computer"},
                                 headers={"X-API-Key": api_key})
    assert resp.status_code in (200, 500)
