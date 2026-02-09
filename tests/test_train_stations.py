from __future__ import annotations


from gzm_client.utils.sql_cache import StopsSqlCache


def test_train_station_best_match(tmp_path) -> None:
    db_path = tmp_path / "stops.db"
    cache = StopsSqlCache(str(db_path))

    cache.save_train_stations(
        [
            {
                "name": "Będzin Miasto",
                "sid": "SID123",
                "lat": 50.32,
                "lon": 19.13,
                "platforms": [{"lat": 50.3201, "lon": 19.1301}],
                "platforms_qty": 1,
            },
            {
                "name": "Katowice",
                "lat": 50.259,
                "lon": 19.017,
                "platforms": [],
                "platforms_qty": 0,
            },
        ]
    )

    exact = cache.find_train_station_best_match("Będzin Miasto")
    assert exact is not None
    assert exact["name"] == "Będzin Miasto"
    assert exact.get("sid") == "SID123"
    assert exact.get("match", {}).get("kind") == "exact"

    fuzzy = cache.find_train_station_best_match("Bedzin miast")
    assert fuzzy is not None
    assert fuzzy["name"] == "Będzin Miasto"
