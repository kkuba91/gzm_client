"""Python API for mstops-compatible functionality.

This module ports the behavior of the standalone mstops.py script into a library:
- Methods can print to stdout (same as mstops.py)
- The same methods can return JSON-serializable dictionaries
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import requests
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table

from .constants import (
    ALL_STOPS_URL,
    BIKES_NEARBY_METERS,
    DEPARTURE_URL,
    GZM_BIKES_CITIES_URL,
    GZM_BIKES_CITY_STATUS_FULL_URL,
    GZM_BIKES_STATION_STATUS_FULL_URL,
    GZM_BIKES_STATION_STATUS_SHORT_URL,
    GZM_BIKES_STATIONS_LOCATIONS_URL,
    STOP_URL,
    VEHICLE_ALL_DID_URL,
    VEHICLE_VID_URL,
    VEHICLE_TYPE,
    TICKET_MACHINES_URL,
)
from .transportation.bikes.station import BikeStation, BikeStationNearby
from .transportation.parsers import (
    find_nearby_bike_stations,
    parse_departures,
    parse_stop_info,
)
from .transportation.stop import Departure
from .transportation.vehicle import VehicleTripSummary
from .utils.sql_cache import StopsSqlCache


class GzmClient:
    """High-level client exposing mstops-like commands."""

    @staticmethod
    def _run_async(
        coro: "asyncio.Future[Any] | asyncio.coroutines.Coroutine[Any, Any, Any]",
    ) -> Any | None:
        """Run coroutine from sync code.

        Returns None when already inside a running event loop (so callers can fall back
        to synchronous implementations).
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        return None

    @staticmethod
    def _parse_bike_stations_locations_payload(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("Unexpected station_information format (expected dict).")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("Missing or invalid 'data' field in station_information.")
        stations = data.get("stations")
        if not isinstance(stations, list):
            raise ValueError(
                "Missing or invalid 'stations' field in station_information."
            )
        return stations

    @staticmethod
    def _parse_bike_stations_status_payload(payload: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("Unexpected station_status format (expected dict).")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("Missing or invalid 'data' field in station_status.")
        stations = data.get("stations")
        if not isinstance(stations, list):
            raise ValueError("Missing or invalid 'stations' field in station_status.")
        status_by_id: dict[str, dict[str, Any]] = {}
        for s in stations:
            if not isinstance(s, dict):
                continue
            sid = s.get("station_id")
            if sid is None:
                continue
            status_by_id[str(sid)] = s
        return status_by_id

    async def _load_bike_station_snapshots_async(
        self,
    ) -> tuple[list[dict[str, Any]] | None, dict[str, dict[str, Any]] | None]:
        """Fetch Nextbike station locations + statuses concurrently."""
        try:
            timeout = httpx.Timeout(15.0)
            limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
            async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
                loc_req = client.get(GZM_BIKES_STATIONS_LOCATIONS_URL)
                status_req = client.get(GZM_BIKES_STATION_STATUS_SHORT_URL)
                loc_resp, status_resp = await asyncio.gather(loc_req, status_req)
                loc_resp.raise_for_status()
                status_resp.raise_for_status()
                stations = self._parse_bike_stations_locations_payload(loc_resp.json())
                status_by_id = self._parse_bike_stations_status_payload(
                    status_resp.json()
                )
                return stations, status_by_id
        except Exception:
            return None, None

    async def _fetch_stop_snippets_async(self, stop_ids: list[str]) -> dict[str, str]:
        """Fetch many stop HTML snippets concurrently (best-effort)."""
        out: dict[str, str] = {}
        if not stop_ids:
            return out
        sem = asyncio.Semaphore(10)
        timeout = httpx.Timeout(8.0)
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:

            async def one(sid: str) -> tuple[str, str]:
                async with sem:
                    r = await client.get(STOP_URL.format(sid))
                    r.raise_for_status()
                    return sid, r.text

            results = await asyncio.gather(
                *(one(sid) for sid in stop_ids), return_exceptions=True
            )
            for item in results:
                if isinstance(item, Exception):
                    continue
                sid, text = item
                out[str(sid)] = text
        return out

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000.0
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        dphi = math.radians(float(lat2) - float(lat1))
        dlambda = math.radians(float(lon2) - float(lon1))
        a = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return r * c

    def __init__(
        self,
        db_path: str | None = None,
        session: requests.Session | None = None,
        bikes_nearby_meters: int = BIKES_NEARBY_METERS,
    ) -> None:
        """Initialize the client.

        Args:
            db_path: Path to the SQLite cache file. Defaults to ``stops.db``.
            session: Optional shared ``requests.Session`` for HTTP calls. If omitted,
                a new session is created.
            bikes_nearby_meters: Radius (in meters) used when searching for nearby
                Nextbike stations in stop/junction methods.

        Returns:
            None
        """
        self.db_path = db_path or "stops.db"
        self.cache = StopsSqlCache(self.db_path)
        self.session = session or requests.Session()
        self.bikes_nearby_meters = bikes_nearby_meters
        self._console = Console()

    def _print(self, *args: Any, **kwargs: Any) -> None:
        self._console.print(*args, **kwargs)

    def _warn(self, message: str) -> None:
        self._console.print(f"[yellow]Warning:[/yellow] {message}")

    def _error(self, message: str) -> None:
        self._console.print(f"[red]Error:[/red] {message}")

    # -----------------------------
    # Update / cache
    # -----------------------------
    def update_api(self, to_stdout: bool = False) -> dict[str, Any]:
        """Fetch the most static data from remote APIs and update the local cache.

        Updates the local SQLite cache with the mstops stop list and, best-effort,
        ticket machines and Nextbike city/region metadata.

        Args:
            to_stdout: When True, prints status using Rich (mstops-like behavior).

        Returns:
            JSON-serializable dict describing what was updated and any non-fatal
            errors (e.g. Nextbike/ticket machines failures).

        Raises:
            requests.HTTPError: When the main stop list download fails.
            ValueError: When the stop list payload format is unexpected.
        """
        resp = self.session.get(ALL_STOPS_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("Unexpected mstops payload format (expected list).")

        self.cache.save_stops(data)

        ticket_machines_updated = False
        ticket_machines_error: str | None = None
        ticket_machines_count: int | None = None
        try:
            tm_resp = self.session.get(TICKET_MACHINES_URL, timeout=20)
            tm_resp.raise_for_status()
            tm_payload = tm_resp.json()
            if not isinstance(tm_payload, list):
                raise ValueError(
                    "Unexpected ticket machines payload format (expected list)."
                )
            # payload is list of [lat, lon, name, kind]
            machines = [
                m for m in tm_payload if isinstance(m, (list, tuple)) and len(m) >= 4
            ]
            self.cache.save_ticket_machines(machines)  # type: ignore[arg-type]
            ticket_machines_updated = True
            ticket_machines_count = len(machines)
        except Exception as e:
            ticket_machines_error = str(e)

        bikes_updated = False
        bikes_error: str | None = None
        try:
            regions_payload = self._load_bike_cities_from_api()
            self.cache.save_bike_cities(
                regions_payload["regions"],
                last_updated=regions_payload.get("last_updated"),
                ttl=regions_payload.get("ttl"),
            )
            bikes_updated = True
        except Exception as e:  # keep mstops behavior: non-fatal
            bikes_error = str(e)

        if to_stdout:
            if bikes_updated:
                self._print(
                    Panel(
                        "Updated database from API (stops + bikes).",
                        title="API cached",
                        border_style="green",
                    )
                )
            else:
                self._print(
                    Panel(
                        "Updated database from API (stops).",
                        title="API cached",
                        border_style="green",
                    )
                )
                if bikes_error:
                    self._warn(f"failed to update Nextbike bike data: {bikes_error}")
            if ticket_machines_updated:
                self._print(
                    Panel(
                        f"Ticket machines cached: {ticket_machines_count or 0}",
                        title="SKUP",
                        border_style="green",
                    )
                )
            elif ticket_machines_error:
                self._warn(f"failed to update ticket machines: {ticket_machines_error}")

        return {
            "updated": "api",
            "stops_count": len(data),
            "bikes_updated": bikes_updated,
            "bikes_error": bikes_error,
            "ticket_machines_updated": ticket_machines_updated,
            "ticket_machines_count": ticket_machines_count,
            "ticket_machines_error": ticket_machines_error,
            "db_path": self.db_path,
        }

    def update_file(self, path: str, to_stdout: bool = False) -> dict[str, Any]:
        """Load a JSON dump from disk and update the local cache.

        Args:
            path: Path to a JSON file containing a list payload compatible with mstops.
            to_stdout: When True, prints a short confirmation message.

        Returns:
            JSON-serializable dict describing the update (source, path, count).

        Raises:
            OSError: If the file cannot be read.
            json.JSONDecodeError: If the file is not valid JSON.
            ValueError: If the JSON root is not a list.
        """
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Unexpected mstops file format (expected JSON list).")
        self.cache.save_stops(data)
        if to_stdout:
            self._print(
                Panel(
                    f"Updated database from file {path}.",
                    title="update_file",
                    border_style="green",
                )
            )
        return {
            "updated": "file",
            "path": str(p),
            "stops_count": len(data),
            "db_path": self.db_path,
        }

    # -----------------------------
    # Stops / junctions
    # -----------------------------
    def list_by_municipality(
        self, city: str, to_stdout: bool = False
    ) -> dict[str, Any]:
        """List grouped stops (junctions) for a municipality.

        Reads from the local cache; run :meth:`update_api` or :meth:`update_file` first.

        Args:
            city: Municipality name.
            to_stdout: When True, prints a table of stop groups.

        Returns:
            JSON-serializable dict with ``city`` and a ``stops`` list.
            If the database is missing, returns ``{"error": "db_missing"}``.
        """
        if not self.cache.exists():
            if to_stdout:
                self._error(
                    "Database does not exist. Run update_file or update_api first."
                )
            return {"error": "db_missing"}

        grouped = self.cache.list_grouped_by_municipality(city)
        if not grouped:
            if to_stdout:
                self._warn(f"No stops found for city: {city}")
            return {"city": city, "stops": []}

        if to_stdout:
            table = Table(border_style="cyan")
            table.add_column("Stop (group of platforms)")
            table.add_column("Platform IDs")
            for item in grouped:
                table.add_row(
                    str(item.get("name", "")),
                    json.dumps(item.get("ids", []), ensure_ascii=False),
                )
            self._print(Panel(table, title=f"Stops in {city}", border_style="cyan"))

        return {"city": city, "stops": grouped}

    def junction(self, name: str, to_stdout: bool = False) -> dict[str, Any]:
        """Show information for a stop/junction across all platform variants.

        For each matching platform, this method fetches and parses stop metadata
        (lines/type) and optionally aggregates nearby Nextbike stations and cached
        ticket machines.

        Args:
            name: Stop/junction name.
            to_stdout: When True, prints Rich panels/tables (mstops-like behavior).

        Returns:
            JSON-serializable dict containing the query ``name`` and a ``variants`` list.
            If the database is missing, returns ``{"error": "db_missing"}``.
            If ``name`` is empty/blank, returns ``{"error": "invalid_name"}``.
        """
        if not self.cache.exists():
            if to_stdout:
                self._error(
                    "Database does not exist. Run update_file or update_api first."
                )
            return {"error": "db_missing"}

        name = (name or "").strip()
        if not name:
            if to_stdout:
                self._warn("Provide a junction stop name.")
            return {"error": "invalid_name"}

        variants = self.cache.find_stop_variants_by_name(name)
        if not variants:
            if to_stdout:
                self._warn(f"Stop not found with name: {name}")
            return {"name": name, "variants": []}

        renderables: list[Any] = []

        bike_stations, bike_status = self._try_load_bike_station_snapshots()
        stop_ids = [str(v.get("id")) for v in variants if v.get("id") is not None]
        snippets_by_id: dict[str, str] = {}
        async_result = self._run_async(self._fetch_stop_snippets_async(stop_ids))
        if isinstance(async_result, dict):
            snippets_by_id = async_result
        junction_points: list[tuple[float, float]] = []
        nearby_station_occurrences: dict[str, dict[str, Any]] = {}

        # Stop platforms process
        results: list[dict[str, Any]] = []
        for v in variants:
            stop_id = v["id"]
            alt_id = v["alt_id"]
            stop_name = v["name"]
            mun = v["municipality"]
            lat = v["lat"]
            lon = v["lon"]
            if lat is not None and lon is not None:
                junction_points.append((float(lat), float(lon)))

            tm_near: dict[str, Any] | None = None
            tm_close = False
            tm_distance_m: float | None = None
            tm_name: str | None = None
            if lat is not None and lon is not None:
                tm_near = self.cache.find_nearest_ticket_machine(
                    float(lat), float(lon), max_distance_m=300
                )
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

            stop_snippet = snippets_by_id.get(str(stop_id)) or self._fetch_stop_snippet(
                stop_id
            )
            stop_info = parse_stop_info(stop_snippet)
            lines = stop_info.get("lines") or []
            lt = stop_info.get("type") or "N/A"
            lt = "N/A" if isinstance(lt, str) and "br>" in lt else lt

            # Nearby bike stations finding
            nearby_models: list[BikeStationNearby] = []
            if bike_stations and bike_status and lat is not None and lon is not None:
                region_id = self.cache.find_unambiguous_bike_city_id_by_name_part(mun)
                nearby_models = [
                    BikeStationNearby.from_dict(d)
                    for d in find_nearby_bike_stations(
                        lat,
                        lon,
                        bike_stations,
                        bike_status,
                        max_distance_m=self.bikes_nearby_meters,
                        region_id=region_id,
                    )
                ]
                for s in nearby_models:
                    key = str(s.station_id or s.short_name or s.name or "").strip()
                    if not key:
                        continue
                    occ = nearby_station_occurrences.get(key)
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
                        nearby_station_occurrences[key] = occ
                    occ["distance_samples"].append(float(s.distance_m or 0.0))

            if to_stdout:
                header = f"Stop: {stop_name} | ID={stop_id} | ALT={alt_id} | TYPE={lt} | {mun}"
                tm_status = "YES" if tm_close else "NO"
                if tm_close and tm_distance_m is not None:
                    tm_status = f"YES ({int(round(tm_distance_m))}m)"
                renderables.append(
                    Panel(
                        f"Lines: {', '.join(lines) if lines else 'N/A'}\n"
                        f"Ticket machine: {tm_status}{(' - ' + tm_name) if tm_name else ''}",
                        title=header,
                        border_style="blue",
                    )
                )

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
                    },
                    "info": stop_info,
                    "nearby_bikes": [asdict(s) for s in nearby_models],
                }
            )

        if to_stdout and nearby_station_occurrences:
            bt = Table(
                title="Nearby bike stations",
                border_style="magenta",
                title_justify="left",
            )
            bt.add_column("Id")
            bt.add_column("Station")
            bt.add_column("Location")
            bt.add_column("Distance")
            bt.add_column("Bikes")
            bt.add_column("Docks")

            rows: list[tuple[float, dict[str, Any]]] = []
            for occ in nearby_station_occurrences.values():
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
                            self._haversine_m(p[0], p[1], stat_lat, stat_lon)
                            for p in junction_points
                        ]
                        avg_dist_m = sum(dists) / len(dists) if dists else None
                    except Exception:
                        avg_dist_m = None
                if avg_dist_m is None:
                    samples = occ.get("distance_samples") or []
                    if isinstance(samples, list) and samples:
                        avg_dist_m = float(sum(samples) / len(samples))
                    else:
                        avg_dist_m = 10**9
                rows.append((avg_dist_m, occ))

            rows.sort(key=lambda x: x[0])
            for avg_dist_m, occ in rows:
                short_name = (
                    occ.get("short_name") or occ.get("name") or occ.get("station_id")
                )
                location = occ.get("position")
                bikes_out = (
                    occ.get("bikes_available")
                    if occ.get("bikes_available") is not None
                    else "?"
                )
                docks_out = (
                    occ.get("docks_available")
                    if occ.get("docks_available") is not None
                    else "?"
                )
                dist_out = "?" if avg_dist_m >= 10**8 else f"{int(round(avg_dist_m))}m"
                bt.add_row(
                    str(occ.get("station_id")),
                    str(short_name),
                    str(location),
                    dist_out,
                    str(bikes_out),
                    str(docks_out),
                )
            renderables.append("")
            renderables.append(bt)

        if to_stdout:
            title = f"Junction for '{name}' ({len(variants)} stops found)."
            self._print(Panel(Group(*renderables), title=title, border_style="cyan"))

        return {"name": name, "variants": results}

    def stop_departures(
        self, stop_id: str | int, to_stdout: bool = False
    ) -> dict[str, Any]:
        """Fetch and parse live departures for a single stop/platform id.

        Args:
            stop_id: Numeric stop/platform id.
            to_stdout: When True, prints a departures table and optional nearby info.

        Returns:
            JSON-serializable dict with keys:
            - ``stop`` (cached metadata + ticket machine fields)
            - ``departures`` (parsed departures; may be empty)
            - ``nearby_bikes`` (best-effort Nextbike station list)
            If the database is missing, returns ``{"error": "db_missing"}``.
            If ``stop_id`` is invalid, returns ``{"error": "invalid_stop_id"}``.
        """
        if not self.cache.exists():
            if to_stdout:
                self._error(
                    "Database does not exist. Run update_file or update_api first."
                )
            return {"error": "db_missing"}

        stop_id_str = str(stop_id).strip()
        if not stop_id_str.isdigit():
            if to_stdout:
                self._warn("Invalid 'id'.")
            return {"error": "invalid_stop_id"}

        stop_row = self.cache.find_stop_by_id(stop_id_str)
        if not stop_row:
            if to_stdout:
                self._warn(f"Stop not found for stop_id: {stop_id_str}")
            return {"stop_id": stop_id_str, "departures": []}

        tm_near: dict[str, Any] | None = None
        tm_close = False
        tm_distance_m: float | None = None
        tm_name: str | None = None
        if stop_row.get("lat") is not None and stop_row.get("lon") is not None:
            tm_near = self.cache.find_nearest_ticket_machine(
                float(stop_row["lat"]), float(stop_row["lon"]), max_distance_m=300
            )
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

        bike_stations, bike_status = self._try_load_bike_station_snapshots()

        url = DEPARTURE_URL.format(stop_row["id"])
        html_text = ""
        try:
            resp = self.session.get(url, timeout=6)
            resp.raise_for_status()
            html_text = resp.text
        except Exception as e:
            if to_stdout:
                self._warn(f"Fetch error: {e}")

        deps = [Departure.from_dict(d) for d in parse_departures(html_text)]

        renderables: list[Any] = []
        # Departures table
        if to_stdout and deps:
            dt = Table(title="Departures", border_style="blue", title_justify="left")
            dt.add_column("DID")
            dt.add_column("Line")
            dt.add_column("Type")
            dt.add_column("Destination")
            dt.add_column("Arrival Time")
            for d in deps:
                dt.add_row(
                    str(d.did or ""),
                    str(d.line or ""),
                    VEHICLE_TYPE.get(d.line_type, "Bus"),
                    str(d.destination or ""),
                    str(d.time or ""),
                )
            renderables.append(dt)

        # Ticket machine info
        if to_stdout:
            tm_status = "YES" if tm_close else "NO"
            if tm_close and tm_distance_m is not None:
                tm_status = f"YES ({int(round(tm_distance_m))}m)"
            renderables.append(
                f"Ticket machine: {tm_status}{(' - ' + tm_name) if tm_name else ''}\n"
            )
        stop_out = dict(stop_row)
        stop_out["ticket_machine"] = tm_close
        stop_out["ticket_machine_distance_m"] = tm_distance_m
        stop_out["ticket_machine_name"] = tm_name

        # Nearby bike stations
        nearby_models: list[BikeStationNearby] = []
        if (
            bike_stations
            and bike_status
            and stop_row.get("lat") is not None
            and stop_row.get("lon") is not None
        ):
            region_id = self.cache.find_unambiguous_bike_city_id_by_name_part(
                stop_row["municipality"]
            )
            nearby_models = [
                BikeStationNearby.from_dict(d)
                for d in find_nearby_bike_stations(
                    stop_row["lat"],
                    stop_row["lon"],
                    bike_stations,
                    bike_status,
                    max_distance_m=self.bikes_nearby_meters,
                    region_id=region_id,
                )
            ]
            if to_stdout:
                bt = Table(
                    title="Nearby bike stations",
                    border_style="magenta",
                    title_justify="left",
                )
                bt.add_column("Id")
                bt.add_column("Station")
                bt.add_column("Location")
                bt.add_column("Distance")
                bt.add_column("Bikes")
                bt.add_column("Docks")
                for s in nearby_models:
                    location = s.position
                    dist = int(round(s.distance_m))
                    bikes_out = (
                        s.bikes_available if s.bikes_available is not None else "?"
                    )
                    docks_out = (
                        s.docks_available if s.docks_available is not None else "?"
                    )
                    short_name = s.short_name or s.name or s.station_id
                    bt.add_row(
                        str(s.station_id),
                        str(short_name),
                        str(location),
                        f"{dist}m",
                        str(bikes_out),
                        str(docks_out),
                    )
                renderables.append(bt)

        if to_stdout and deps:
            header = f"Stop: {stop_row['name']} | ID={stop_row['id']} | ALT={stop_row['alt_id']} | {stop_row['municipality']}"
            self._print(Panel(Group(*renderables), title=header, border_style="blue"))

        return {
            "stop": stop_out,
            "ticket_machine": tm_close,
            "nearby_bikes": [asdict(s) for s in nearby_models],
            "departures": [asdict(d) for d in deps],
        }

    # -----------------------------
    # Vehicle by did
    # -----------------------------
    def go_for_did(self, did: str, to_stdout: bool = False) -> dict[str, Any]:
        """Resolve a live vehicle summary by departure id (DID).

        Args:
            did: Departure id (numeric), as returned by :meth:`stop_departures`.
            to_stdout: When True, prints a summary panel.

        Returns:
            JSON-serializable dict created from :class:`VehicleTripSummary`.
            If ``did`` is invalid, returns ``{"error": "invalid_did"}``.
            If the fetch fails, returns ``{"error": "fetch_failed", "details": ...}``.
        """
        did_s = str(did).strip()
        if not did_s.isdigit():
            if to_stdout:
                self._warn("Provide a valid did (numeric).")
            return {"error": "invalid_did"}

        url_all = VEHICLE_ALL_DID_URL.format(did_s)
        try:
            resp = self.session.get(url_all, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            if to_stdout:
                self._error(f"Error fetching VEHICLE_ALL_DID_URL: {e}")
            return {"error": "fetch_failed", "details": str(e)}

        if not isinstance(data, dict):
            if to_stdout:
                self._error("Unexpected data format (expected dict).")
            return {"error": "unexpected_format"}

        vehicle = data.get("vehicle")
        if not isinstance(vehicle, dict):
            if to_stdout:
                self._error("Missing or invalid 'vehicle' item in response.")
            return {"error": "missing_vehicle"}

        vehicle_id = vehicle.get("id")
        if vehicle_id:
            url_vid = VEHICLE_VID_URL.format(vehicle_id)
            try:
                resp2 = self.session.get(url_vid, timeout=10)
                resp2.raise_for_status()
                upd = resp2.json()
                if isinstance(upd, list) and upd and isinstance(upd[0], dict):
                    vehicle.update(upd[0])
            except Exception as e:
                if to_stdout:
                    self._warn(f"error fetching VEHICLE_VID_URL: {e}")

        summary = VehicleTripSummary.from_vehicle_all_payload(did_s, data)
        out = asdict(summary)

        if to_stdout:
            next_stop = summary.next_stop or {}
            body = "\n".join(
                [
                    f"line: {summary.line_out}  |  did={did_s}  |  id={summary.vehicle_id or ''}  |  type={summary.vehicle_type or ''}",
                    f"route: '{summary.route_name or ''}'",
                    f"next stop: '{next_stop.get('name', '')}' with time: {next_stop.get('time', '')}",
                    f"deviation: {next_stop.get('deviation', '')}",
                    f"position: ({summary.lat}, {summary.lon})",
                ]
            )
            title = f"{summary.vehicle_type or 'Vehicle'}: {summary.line_out or ''}"
            self._print(Panel(body, border_style="magenta", title=title))

        return out

    # -----------------------------
    # Bikes (Nextbike)
    # -----------------------------
    def bikes_city(self, city_prefix: str, to_stdout: bool = False) -> dict[str, Any]:
        """Fetch and summarize Nextbike status for a city/region.

        City/region resolution uses the local cache populated by :meth:`update_api`.
        Live status is fetched from the Nextbike endpoint.

        Args:
            city_prefix: City name prefix used for lookup (e.g. ``"Będzin"``).
            to_stdout: When True, prints a compact summary.

        Returns:
            JSON-serializable dict including the query, resolution, and summary.
            If the database is missing, returns ``{"error": "db_missing"}``.
            If the prefix is empty, returns ``{"error": "invalid_city_prefix"}``.
        """
        prefix = (city_prefix or "").strip()
        if not prefix:
            if to_stdout:
                self._warn("Provide a city name (prefix), e.g. 'Będzin'.")
            return {"error": "invalid_city_prefix"}

        if not self.cache.exists():
            if to_stdout:
                self._error(
                    "Database does not exist. Run update_api first (to fetch the city/region list)."
                )
            return {"error": "db_missing"}

        city_id, full_name = self.cache.resolve_bike_city_id_by_prefix(prefix)
        if city_id is None:
            matches = self.cache.find_bike_city_ids_by_name_prefix(prefix)
            if to_stdout:
                if not matches:
                    self._warn(f"No city found starting with: {prefix}")
                else:
                    self._warn(f"Ambiguous match for: {prefix}")
                    for rid, nm in matches:
                        self._print(f"  - {nm} (id={rid})")
            return {
                "query": prefix,
                "resolved": None,
                "matches": [{"region_id": rid, "name": nm} for rid, nm in matches],
            }

        try:
            payload = self._load_bike_city_status_full_from_api(city_id)
        except Exception as e:
            if to_stdout:
                self._error(f"Error fetching Nextbike city status: {e}")
            return {"error": "fetch_failed", "details": str(e)}

        compact = self._compact_bike_city_status(payload, requested_city_id=city_id)
        if to_stdout:
            self._print_bike_city_status_summary(compact)
        return {
            "query": prefix,
            "resolved": {"region_id": city_id, "name": full_name},
            "summary": compact,
        }

    def bikes_station(self, station_id: str, to_stdout: bool = False) -> dict[str, Any]:
        """Fetch and summarize Nextbike status for a single station.

        Args:
            station_id: Nextbike station id (numeric).
            to_stdout: When True, prints a compact summary.

        Returns:
            JSON-serializable dict with the query and a compact station summary.
            If ``station_id`` is invalid, returns ``{"error": "invalid_station_id"}``.
            If the fetch fails, returns ``{"error": "fetch_failed", "details": ...}``.
        """
        sid = str(station_id).strip()
        if not sid.isdigit():
            if to_stdout:
                self._warn("Provide a valid station_id (numeric), e.g. 448593862")
            return {"error": "invalid_station_id"}

        try:
            payload = self._load_bike_station_status_full_from_api(sid)
        except Exception as e:
            if to_stdout:
                self._error(f"Error fetching Nextbike station status: {e}")
            return {"error": "fetch_failed", "details": str(e)}

        compact = self._compact_bike_station_status(payload, requested_station_id=sid)
        if to_stdout:
            self._print_bike_station_status_summary(compact)
        return {"query": {"station_id": sid}, "summary": compact}

    # -----------------------------
    # Internals
    # -----------------------------
    def _load_bike_cities_from_api(self) -> dict[str, Any]:
        resp = self.session.get(GZM_BIKES_CITIES_URL, timeout=10)
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

    def _try_load_bike_station_snapshots(
        self,
    ) -> tuple[list[dict[str, Any]] | None, dict[str, dict[str, Any]] | None]:
        async_result = self._run_async(self._load_bike_station_snapshots_async())
        if isinstance(async_result, tuple) and len(async_result) == 2:
            return async_result
        try:
            stations = self._load_bike_stations_locations_from_api()
            status = self._load_bike_stations_status_from_api()
            return stations, status
        except Exception:
            return None, None

    def _load_bike_stations_locations_from_api(self) -> list[dict[str, Any]]:
        resp = self.session.get(GZM_BIKES_STATIONS_LOCATIONS_URL, timeout=15)
        resp.raise_for_status()
        return self._parse_bike_stations_locations_payload(resp.json())

    def _load_bike_stations_status_from_api(self) -> dict[str, dict[str, Any]]:
        resp = self.session.get(GZM_BIKES_STATION_STATUS_SHORT_URL, timeout=15)
        resp.raise_for_status()
        return self._parse_bike_stations_status_payload(resp.json())

    def _load_bike_city_status_full_from_api(self, city_id: str) -> dict[str, Any]:
        url = GZM_BIKES_CITY_STATUS_FULL_URL.format(city_id)
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected nextbike-live.json format (expected dict).")
        return payload

    def _load_bike_station_status_full_from_api(
        self, station_id: str
    ) -> dict[str, Any]:
        url = GZM_BIKES_STATION_STATUS_FULL_URL.format(station_id)
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected nextbike-live.json format (expected dict).")
        return payload

    def _fetch_stop_snippet(self, stop_id: str) -> str:
        url = STOP_URL.format(stop_id)
        resp = self.session.get(url, timeout=8)
        resp.raise_for_status()
        return resp.text

    def _compact_bike_city_status(
        self, payload: dict[str, Any], requested_city_id: str | None = None
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

        compact_places = []
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

    def _compact_bike_station_status(
        self,
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
        compact_bikes = []
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

    def _print_bike_city_status_summary(self, compact: dict[str, Any]) -> None:
        if "error" in compact:
            self._error(str(compact["error"]))
            return
        country = compact.get("country") or {}
        city = compact.get("city") or {}
        city_summary = (
            f"system: {country.get('name')},  "
            f"hotline: {country.get('hotline')},  "
            f"stations: {city.get('num_places')},  "
            f"booked: {city.get('booked')},  "
            f"available bikes: {city.get('available')}\n"
            "stations:\n"
        )
        bike_stations = "\n".join(
            [
                str(BikeStation.from_dict(station))
                for station in compact.get("stations") or []
            ]
        )
        title = f"Bike region: {city.get('name')} (uid={city.get('uid')})"
        self._print(
            Panel(f"{city_summary}{bike_stations}", border_style="blue", title=title)
        )

    def _print_bike_station_status_summary(self, compact: dict[str, Any]) -> None:
        if "error" in compact:
            self._error(str(compact["error"]))
            return
        ctx = compact.get("context") or {}
        city = ctx.get("city") or {}
        country = ctx.get("country") or {}
        station = BikeStation.from_dict(compact.get("station") or {})
        self._print(
            Panel(
                f"Region: {city.get('name')} | (uid={city.get('uid')}) | system: {country.get('name')} | hotline: {country.get('hotline')}\n{station}",
                border_style="blue",
                title=f"Bike station: id={station.station_id} | name={station.name}",
            )
        )
