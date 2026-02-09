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
@patch("gzm_client.client.requests.Session.post")
def test_update_api_success(mock_post, mock_get, client):
    # Stops payload
    stops_resp = MagicMock()
    stops_resp.status_code = 200
    stops_resp.json.return_value = [{"id": 1, "name": "Test Stop"}]

    # Ticket machines payload: [[lat, lon, name, kind], ...]
    tm_resp = MagicMock()
    tm_resp.status_code = 200
    tm_resp.json.return_value = [[50.0, 19.0, "TM1", "biletomat"]]

    # Nextbike cities payload
    bikes_resp = MagicMock()
    bikes_resp.status_code = 200
    bikes_resp.json.return_value = {
        "data": {"regions": []},
        "last_updated": 0,
        "ttl": 0,
    }

    mock_get.side_effect = [stops_resp, tm_resp, bikes_resp]

    # Overpass payload
    overpass_resp = MagicMock()
    overpass_resp.status_code = 200
    overpass_resp.json.return_value = {"elements": []}
    mock_post.return_value = overpass_resp

    with (
        patch.object(client.cache, "save_stops") as save_stops,
        patch.object(client.cache, "save_ticket_machines") as save_tms,
        patch.object(client.cache, "save_bike_cities") as save_bikes,
        patch.object(client.cache, "save_train_stations") as save_trains,
        patch.object(client.cache, "save_taxi_stands") as save_taxi,
    ):
        save_stops.return_value = None
        save_tms.return_value = None
        save_bikes.return_value = None
        save_trains.return_value = None
        save_taxi.return_value = None
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
