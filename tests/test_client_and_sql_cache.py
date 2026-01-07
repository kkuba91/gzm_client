import pytest
from unittest.mock import patch, MagicMock
from gzm_client.client import GzmClient


# -------------------
# GzmClient API tests
# -------------------
@pytest.fixture
def client():
    return GzmClient(db_path=":memory:")


@patch("gzm_client.client.requests.Session.get")
def test_update_api_success(mock_get, client):
    # Mock stop list response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"id": 1, "name": "Test Stop"}]
    mock_get.return_value = mock_resp
    # Patch save_stops to avoid DB
    with patch.object(client.cache, "save_stops") as save_stops:
        save_stops.return_value = None
        result = client.update_api()
        assert result["updated"] == "api"
        assert result["stops_count"] == 1


@patch("gzm_client.client.requests.Session.get")
def test_update_api_invalid_payload(mock_get, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"unexpected": "dict"}
    mock_get.return_value = mock_resp
    with pytest.raises(ValueError):
        client.update_api()
