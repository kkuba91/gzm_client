"""Junction-related models.

In mstops-compatible operations a junction is represented by a stop name with
multiple variants (different ids/platforms).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import requests

from ..utils.utils import haversine_m, run_async
from .bikes.api import try_load_bike_station_snapshots
from .bikes.station import BikeStationNearby
from .parsers import find_nearby_bike_stations, parse_stop_info
from .stop import fetch_stop_snippet, fetch_stop_snippets_async


@dataclass(frozen=True)
class JunctionQuery:
    name: str


class JunctionCache(Protocol):
    def find_stop_variants_by_name(self, name: str) -> list[dict[str, Any]]: ...

    def find_nearest_ticket_machine(
        self, lat: float, lon: float, max_distance_m: int = 300
    ) -> dict[str, Any] | None: ...

    def find_nearest_taxi_stand(
        self, lat: float, lon: float, max_distance_m: int = 150
    ) -> dict[str, Any] | None: ...

    def find_unambiguous_bike_city_id_by_name_part(
        self, name_part: str
    ) -> str | None: ...


@dataclass(frozen=True)
class JunctionResolved:
    """Resolved junction details (data only; printing handled by the client)."""

    name: str
    variants: list[dict[str, Any]]
    junction_points: list[tuple[float, float]]
    nearby_station_occurrences: dict[str, dict[str, Any]]

    def public_result(self) -> dict[str, Any]:
        return {"name": self.name, "variants": self.variants}


def _station_occurrence_key(s: BikeStationNearby) -> str:
    key = str(s.station_id or s.short_name or s.name or "").strip()
    return key


def _merge_nearby_station_occurrences(
    occurrences: dict[str, dict[str, Any]],
    nearby_models: list[BikeStationNearby],
) -> None:
    for s in nearby_models:
        key = _station_occurrence_key(s)
        if not key:
            continue
        occ = occurrences.get(key)
        if occ is None:
            occ = {
                "station_id": s.station_id,
                "name": s.name,
                "short_name": s.short_name,
                "position": s.position,
                "bikes_available": s.bikes_available,
                "docks_available": s.docks_available,
                "distance_samples": [],
            }
            occurrences[key] = occ
        occ["distance_samples"].append(float(s.distance_m or 0.0))


def _avg_distance_m_for_occurrence(
    occ: dict[str, Any],
    junction_points: list[tuple[float, float]],
) -> float:
    pos = occ.get("position")
    avg_dist_m: float | None = None
    if (
        junction_points
        and isinstance(pos, list)
        and len(pos) == 2
        and pos[0] is not None
        and pos[1] is not None
    ):
        try:
            stat_lat = float(pos[0])
            stat_lon = float(pos[1])
            dists = [
                haversine_m(p[0], p[1], stat_lat, stat_lon) for p in junction_points
            ]
            avg_dist_m = sum(dists) / len(dists) if dists else None
        except Exception:
            avg_dist_m = None
    if avg_dist_m is None:
        samples = occ.get("distance_samples") or []
        if isinstance(samples, list) and samples:
            try:
                avg_dist_m = float(sum(samples) / len(samples))
            except Exception:
                avg_dist_m = None
    return avg_dist_m if avg_dist_m is not None else 10**9


def sort_nearby_bike_occurrences(
    nearby_station_occurrences: dict[str, dict[str, Any]],
    junction_points: list[tuple[float, float]],
) -> list[tuple[float, dict[str, Any]]]:
    """Sort aggregated bike station occurrences by average distance."""
    rows: list[tuple[float, dict[str, Any]]] = []
    for occ in nearby_station_occurrences.values():
        rows.append((_avg_distance_m_for_occurrence(occ, junction_points), occ))
    rows.sort(key=lambda x: x[0])
    return rows


def resolve_junction_details(
    cache: JunctionCache,
    session: requests.Session,
    name: str,
    bikes_nearby_meters: int,
    ticket_machine_max_distance_m: int = 300,
) -> JunctionResolved:
    """Resolve junction platforms, parsed info, ticket machines and nearby bikes."""

    variants = cache.find_stop_variants_by_name(name)
    if not variants:
        return JunctionResolved(
            name=name,
            variants=[],
            junction_points=[],
            nearby_station_occurrences={},
        )

    bike_stations, bike_status = try_load_bike_station_snapshots(session)

    stop_ids = [str(v.get("id")) for v in variants if v.get("id") is not None]
    snippets_by_id: dict[str, str] = {}
    async_result = run_async(fetch_stop_snippets_async(stop_ids))
    if isinstance(async_result, dict):
        snippets_by_id = async_result

    junction_points: list[tuple[float, float]] = []
    nearby_station_occurrences: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []

    for v in variants:
        stop_id = v.get("id")
        alt_id = v.get("alt_id")
        stop_name = v.get("name")
        mun = v.get("municipality")
        lat = v.get("lat")
        lon = v.get("lon")

        if lat is not None and lon is not None:
            try:
                junction_points.append((float(lat), float(lon)))
            except Exception:
                pass

        tm_near: dict[str, Any] | None = None
        tm_close = False
        tm_distance_m: float | None = None
        tm_name: str | None = None
        tm_lat: float | None = None
        tm_lon: float | None = None
        if lat is not None and lon is not None:
            try:
                tm_near = cache.find_nearest_ticket_machine(
                    float(lat),
                    float(lon),
                    max_distance_m=ticket_machine_max_distance_m,
                )
            except Exception:
                tm_near = None
            if isinstance(tm_near, dict):
                tm_close = True
                tm_distance_m = (
                    float(tm_near.get("distance_m"))
                    if tm_near.get("distance_m") is not None
                    else None
                )
                tm_name = (
                    str(tm_near.get("name"))
                    if tm_near.get("name") is not None
                    else None
                )
                try:
                    tm_lat = (
                        float(tm_near.get("lat"))
                        if tm_near.get("lat") is not None
                        else None
                    )
                except Exception:
                    tm_lat = None
                try:
                    tm_lon = (
                        float(tm_near.get("lon"))
                        if tm_near.get("lon") is not None
                        else None
                    )
                except Exception:
                    tm_lon = None

        taxi_near: dict[str, Any] | None = None
        taxi_close = False
        taxi_distance_m: float | None = None
        taxi_name: str | None = None
        taxi_lat: float | None = None
        taxi_lon: float | None = None
        if lat is not None and lon is not None:
            try:
                taxi_near = cache.find_nearest_taxi_stand(
                    float(lat),
                    float(lon),
                    max_distance_m=150,
                )
            except Exception:
                taxi_near = None
            if isinstance(taxi_near, dict):
                taxi_close = True
                taxi_distance_m = (
                    float(taxi_near.get("distance_m"))
                    if taxi_near.get("distance_m") is not None
                    else None
                )
                taxi_name = (
                    str(taxi_near.get("name"))
                    if taxi_near.get("name") is not None
                    else None
                )
                try:
                    taxi_lat = (
                        float(taxi_near.get("lat"))
                        if taxi_near.get("lat") is not None
                        else None
                    )
                except Exception:
                    taxi_lat = None
                try:
                    taxi_lon = (
                        float(taxi_near.get("lon"))
                        if taxi_near.get("lon") is not None
                        else None
                    )
                except Exception:
                    taxi_lon = None

        stop_info: dict[str, Any]
        if stop_id is None:
            stop_info = {"name": None, "platform": None, "type": None, "lines": []}
        else:
            stop_id_s = str(stop_id)
            stop_snippet = snippets_by_id.get(stop_id_s) or fetch_stop_snippet(
                session, stop_id_s
            )
            stop_info = parse_stop_info(stop_snippet)

        nearby_models: list[BikeStationNearby] = []
        if bike_stations and bike_status and lat is not None and lon is not None:
            region_id = cache.find_unambiguous_bike_city_id_by_name_part(str(mun or ""))
            nearby_models = [
                BikeStationNearby.from_dict(d)
                for d in find_nearby_bike_stations(
                    float(lat),
                    float(lon),
                    bike_stations,
                    bike_status,
                    max_distance_m=bikes_nearby_meters,
                    region_id=region_id,
                )
            ]
            _merge_nearby_station_occurrences(nearby_station_occurrences, nearby_models)

        results.append(
            {
                "stop": {
                    "id": stop_id,
                    "alt_id": alt_id,
                    "name": stop_name,
                    "municipality": mun,
                    "lat": lat,
                    "lon": lon,
                    "ticket_machine": tm_close,
                    "ticket_machine_distance_m": tm_distance_m,
                    "ticket_machine_name": tm_name,
                    "ticket_machine_lat": tm_lat,
                    "ticket_machine_lon": tm_lon,
                    "taxi_stand": taxi_close,
                    "taxi_stand_distance_m": taxi_distance_m,
                    "taxi_stand_name": taxi_name,
                    "taxi_stand_lat": taxi_lat,
                    "taxi_stand_lon": taxi_lon,
                },
                "info": stop_info,
                "nearby_bikes": [s.__dict__ for s in nearby_models],
            }
        )

    return JunctionResolved(
        name=name,
        variants=results,
        junction_points=junction_points,
        nearby_station_occurrences=nearby_station_occurrences,
    )
