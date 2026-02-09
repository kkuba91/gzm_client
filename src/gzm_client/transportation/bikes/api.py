from __future__ import annotations

import asyncio
from typing import Any

import httpx
import requests

from ...constants import (
    GZM_BIKES_CITIES_URL,
    GZM_BIKES_CITY_STATUS_FULL_URL,
    GZM_BIKES_STATIONS_LOCATIONS_URL,
    GZM_BIKES_STATION_STATUS_FULL_URL,
    GZM_BIKES_STATION_STATUS_SHORT_URL,
)
from ...utils.utils import run_async
from ..parsers import (
    parse_bike_stations_locations_payload,
    parse_bike_stations_status_payload,
)


def load_bike_cities_from_api(
    session: requests.Session,
    url: str = GZM_BIKES_CITIES_URL,
    timeout: float = 10,
) -> dict[str, Any]:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Nextbike response format (expected dict).")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Missing or invalid 'data' field in Nextbike response.")
    regions = data.get("regions")
    if not isinstance(regions, list):
        raise ValueError("Missing or invalid 'regions' field in Nextbike response.")
    return {
        "regions": regions,
        "last_updated": payload.get("last_updated"),
        "ttl": payload.get("ttl"),
    }


async def load_bike_station_snapshots_async(
    locations_url: str = GZM_BIKES_STATIONS_LOCATIONS_URL,
    status_url: str = GZM_BIKES_STATION_STATUS_SHORT_URL,
    timeout_s: float = 15.0,
) -> tuple[list[dict[str, Any]] | None, dict[str, dict[str, Any]] | None]:
    """Fetch Nextbike station locations + statuses concurrently (best-effort)."""
    try:
        timeout = httpx.Timeout(timeout_s)
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            loc_req = client.get(locations_url)
            status_req = client.get(status_url)
            loc_resp, status_resp = await asyncio.gather(loc_req, status_req)
            loc_resp.raise_for_status()
            status_resp.raise_for_status()
            stations = parse_bike_stations_locations_payload(loc_resp.json())
            status_by_id = parse_bike_stations_status_payload(status_resp.json())
            return stations, status_by_id
    except Exception:
        return None, None


def load_bike_stations_locations_from_api(
    session: requests.Session,
    url: str = GZM_BIKES_STATIONS_LOCATIONS_URL,
    timeout: float = 15,
) -> list[dict[str, Any]]:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return parse_bike_stations_locations_payload(resp.json())


def load_bike_stations_status_from_api(
    session: requests.Session,
    url: str = GZM_BIKES_STATION_STATUS_SHORT_URL,
    timeout: float = 15,
) -> dict[str, dict[str, Any]]:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return parse_bike_stations_status_payload(resp.json())


def try_load_bike_station_snapshots(
    session: requests.Session,
) -> tuple[list[dict[str, Any]] | None, dict[str, dict[str, Any]] | None]:
    async_result = run_async(load_bike_station_snapshots_async())
    if isinstance(async_result, tuple) and len(async_result) == 2:
        return async_result
    try:
        stations = load_bike_stations_locations_from_api(session)
        status = load_bike_stations_status_from_api(session)
        return stations, status
    except Exception:
        return None, None


def load_bike_city_status_full_from_api(
    session: requests.Session,
    city_id: str,
    url_template: str = GZM_BIKES_CITY_STATUS_FULL_URL,
    timeout: float = 20,
) -> dict[str, Any]:
    url = url_template.format(city_id)
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected nextbike-live.json format (expected dict).")
    return payload


def load_bike_station_status_full_from_api(
    session: requests.Session,
    station_id: str,
    url_template: str = GZM_BIKES_STATION_STATUS_FULL_URL,
    timeout: float = 20,
) -> dict[str, Any]:
    url = url_template.format(station_id)
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected nextbike-live.json format (expected dict).")
    return payload
