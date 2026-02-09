from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Bike:
    number: Any
    bike_type: Any
    active: Any
    state: Any
    electric_lock: Any
    board_id: Any
    _only_nr: bool = False

    @staticmethod
    def from_dict(d: dict[str, Any] | str) -> "Bike":
        if d is None:
            return None
        if isinstance(d, str):
            return Bike(
                number=d,
                bike_type=None,
                active=None,
                state=None,
                electric_lock=None,
                board_id=None,
                _only_nr=True,
            )
        return Bike(
            number=d.get("number"),
            bike_type=d.get("bike_type"),
            active=d.get("active"),
            state=d.get("state"),
            electric_lock=d.get("electric_lock"),
            board_id=d.get("board_id"),
        )

    def __repr__(self):
        if self._only_nr:
            return f"{self.number}"
        status = "OK" if self.active and self.state == "ok" else "N/A"
        return f" -> number: {self.number},  type: {self.bike_type},  state: {status},  electric lock: {self.electric_lock},  board_id: {self.board_id}"


def compact_bike_city_status(
    payload: dict[str, Any],
    requested_city_id: str | None = None,
) -> dict[str, Any]:
    countries = payload.get("countries")
    if not isinstance(countries, list) or not countries:
        return {"error": "Missing 'countries' field in Nextbike response."}
    country = countries[0] if isinstance(countries[0], dict) else {}
    cities = country.get("cities")
    if not isinstance(cities, list) or not cities:
        return {"error": "Missing 'cities' field in Nextbike response."}

    chosen_city: dict[str, Any] | None = None
    if requested_city_id is not None:
        try:
            req_int = int(str(requested_city_id))
        except ValueError:
            req_int = None
        if req_int is not None:
            for c in cities:
                if not isinstance(c, dict):
                    continue
                if c.get("uid") == req_int or str(c.get("uid")) == str(
                    requested_city_id
                ):
                    chosen_city = c
                    break
    if chosen_city is None:
        chosen_city = cities[0] if isinstance(cities[0], dict) else {}

    places = chosen_city.get("places")
    if not isinstance(places, list):
        places = []

    compact_places: list[dict[str, Any]] = []
    for p in places:
        if not isinstance(p, dict):
            continue
        compact_places.append(
            {
                "station_id": p.get("uid"),
                "pos": (p.get("lat"), p.get("lng")),
                "station_nr": p.get("number"),
                "available": p.get("bikes_available_to_rent"),
                "rack_size": p.get("bike_racks"),
                "free_racks": p.get("free_racks"),
                "bike_list": p.get("bike_numbers"),
            }
        )

    return {
        "country": {
            "name": country.get("name"),
            "hotline": str(country.get("hotline")).replace(" ", ""),
        },
        "city": {
            "name": chosen_city.get("name"),
            "uid": chosen_city.get("uid"),
            "num_places": chosen_city.get("num_places"),
            "booked": chosen_city.get("booked_bikes"),
            "available": chosen_city.get("available_bikes"),
        },
        "stations": compact_places,
    }


def compact_bike_station_status(
    payload: dict[str, Any],
    requested_station_id: str | None = None,
) -> dict[str, Any]:
    countries = payload.get("countries")
    if not isinstance(countries, list) or not countries:
        return {"error": "Missing 'countries' field in Nextbike response."}
    country = countries[0] if isinstance(countries[0], dict) else {}
    cities = country.get("cities")
    if not isinstance(cities, list) or not cities:
        return {"error": "Missing 'cities' field in Nextbike response."}

    req_int: int | None = None
    if requested_station_id is not None:
        try:
            req_int = int(str(requested_station_id))
        except ValueError:
            req_int = None

    chosen_city: dict[str, Any] | None = None
    chosen_place: dict[str, Any] | None = None

    for c in cities:
        if not isinstance(c, dict):
            continue
        places = c.get("places")
        if not isinstance(places, list):
            continue
        for p in places:
            if not isinstance(p, dict):
                continue
            uid = p.get("uid")
            if req_int is None:
                chosen_city = c
                chosen_place = p
                break
            if uid == req_int or str(uid) == str(requested_station_id):
                chosen_city = c
                chosen_place = p
                break
        if chosen_place is not None:
            break

    if chosen_place is None:
        return {"error": "Station not found in Nextbike response."}

    bike_list = chosen_place.get("bike_list")
    if not isinstance(bike_list, list):
        bike_list = []
    compact_bikes: list[dict[str, Any]] = []
    for b in bike_list:
        if not isinstance(b, dict):
            continue
        compact_bikes.append(
            {
                "number": b.get("number"),
                "bike_type": b.get("bike_type"),
                "active": b.get("active"),
                "state": b.get("state"),
                "electric_lock": b.get("electric_lock"),
                "board_id": b.get("boardcomputer"),
            }
        )

    return {
        "context": {
            "city": {
                "name": (chosen_city or {}).get("name"),
                "uid": (chosen_city or {}).get("uid"),
            },
            "country": {
                "name": country.get("name"),
                "hotline": str(country.get("hotline")).replace(" ", ""),
            },
        },
        "station": {
            "uid": chosen_place.get("uid"),
            "pos": (chosen_place.get("lat"), chosen_place.get("lng")),
            "name": chosen_place.get("name") or chosen_place.get("number"),
            "available": chosen_place.get("bikes_available_to_rent"),
            "rack_size": chosen_place.get("bike_racks"),
            "free_racks": chosen_place.get("free_racks"),
            "bike_list": compact_bikes,
        },
    }
