"""Python API for mstops-compatible functionality.

This module ports the behavior of the standalone mstops.py script into a library:
- Methods can print to stdout (same as mstops.py)
- The same methods can return JSON-serializable dictionaries
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

import requests
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from .constants import (
    ALL_STOPS_URL,
    BIKES_NEARBY_METERS,
    DEPARTURE_URL,
    VEHICLE_TYPE,
    TICKET_MACHINES_URL,
    OVERPASS_URL,
)
from .transportation.bikes.station import BikeStation, BikeStationNearby
from .transportation.bikes.bike import (
    compact_bike_city_status,
    compact_bike_station_status,
)
from .transportation.bikes.api import (
    load_bike_cities_from_api,
    load_bike_city_status_full_from_api,
    load_bike_station_status_full_from_api,
    try_load_bike_station_snapshots,
)
from .transportation.parsers import (
    find_nearby_bike_stations,
    parse_departures,
)
from .transportation.stop import (
    Departure,
)
from .transportation.junction import (
    resolve_junction_details,
    sort_nearby_bike_occurrences,
)
from .transportation.train_station import (
    TrainStation,
    build_train_station_record,
    format_portalpasazera_train_label,
    try_fetch_portalpasazera_departures,
    try_fetch_portalpasazera_sid,
)
from .transportation.vehicle import try_resolve_vehicle_trip_summary
from .utils.sql_cache import StopsSqlCache


class GzmClient:
    """High-level client exposing mstops-like commands."""

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
        ticket machines, Nextbike city/region metadata, and train stations from
        OpenStreetMap via Overpass API.

        Args:
            to_stdout: When True, prints status using Rich (mstops-like behavior).

        Returns:
            JSON-serializable dict describing what was updated and any non-fatal
            errors (e.g. Nextbike/ticket machines/train stations failures).

        Raises:
            requests.HTTPError: When the main stop list download fails.
            ValueError: When the stop list payload format is unexpected.
        """
        resp = self.session.get(ALL_STOPS_URL, timeout=30)
        resp.raise_for_status()
        stops_data = resp.json()
        if not isinstance(stops_data, list):
            raise ValueError("Unexpected mstops payload format (expected list).")

        self.cache.save_stops(stops_data)

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
            regions_payload = load_bike_cities_from_api(self.session)
            self.cache.save_bike_cities(
                regions_payload["regions"],
                last_updated=regions_payload.get("last_updated"),
                ttl=regions_payload.get("ttl"),
            )
            bikes_updated = True
        except Exception as e:  # keep mstops behavior: non-fatal
            bikes_error = str(e)

        train_stations_updated = False
        train_stations_error: str | None = None
        train_stations_count: int | None = None
        train_station_sids_total: int | None = None
        train_station_sids_found: int | None = None
        train_station_sids_error: str | None = None
        try:
            # GZM area coordinates (Katowice region)
            LAT = 50.26983
            LON = 18.99881
            RADIUS = 33000  # meters

            query = f"""[out:json];
(
  node["railway"="station"](around:{RADIUS},{LAT},{LON});
  way["railway"="station"](around:{RADIUS},{LAT},{LON});
  relation["railway"="station"](around:{RADIUS},{LAT},{LON});
  node["railway"="stop"](around:{RADIUS},{LAT},{LON});
);
out center tags;
"""

            response = self.session.post(OVERPASS_URL, data=query, timeout=60)
            response.raise_for_status()
            overpass_data = response.json()

            # Structure by name
            by_name = defaultdict(lambda: {"stations": [], "stops": []})

            for el in overpass_data.get("elements", []):
                tags = el.get("tags", {})
                name = tags.get("name")
                if not name:
                    continue

                if el["type"] == "node":
                    lat = el.get("lat")
                    lon = el.get("lon")
                else:
                    center = el.get("center", {})
                    lat = center.get("lat")
                    lon = center.get("lon")

                if lat is None or lon is None:
                    continue

                if tags.get("railway") == "station":
                    by_name[name]["stations"].append((lat, lon))
                elif tags.get("railway") == "stop":
                    by_name[name]["stops"].append((lat, lon))

            # Build result JSON
            result = []

            for name, items in by_name.items():
                stations = items["stations"]
                stops = items["stops"]

                rec = build_train_station_record(name, stations, stops)
                if rec is not None:
                    result.append(rec)

            # Sort by name
            result.sort(key=lambda x: x["name"])

            # Enrich stations with Portal Pasażera SID (best-effort)
            train_station_sids_total = len(result)
            train_station_sids_found = 0
            if result:
                try:
                    if to_stdout:
                        with Progress(
                            TextColumn("[progress.description]{task.description}"),
                            BarColumn(),
                            "{task.completed}/{task.total}",
                            TimeRemainingColumn(),
                            console=self._console,
                            transient=True,
                        ) as progress:
                            task_id = progress.add_task(
                                "Fetching train station SIDs",
                                total=len(result),
                            )
                            for st in result:
                                name = str(st.get("name") or "").strip()
                                display_name = name[:20].ljust(20)
                                progress.update(
                                    task_id,
                                    description=f"Fetching SID: {display_name}",
                                )
                                sid = try_fetch_portalpasazera_sid(self.session, name)
                                if sid:
                                    st["sid"] = sid
                                    train_station_sids_found += 1
                                progress.advance(task_id)
                    else:
                        for st in result:
                            name = str(st.get("name") or "").strip()
                            sid = try_fetch_portalpasazera_sid(self.session, name)
                            if sid:
                                st["sid"] = sid
                                train_station_sids_found += 1
                except Exception as e:
                    train_station_sids_error = str(e)

            self.cache.save_train_stations(result)
            train_stations_updated = True
            train_stations_count = len(result)
        except Exception as e:  # keep mstops behavior: non-fatal
            train_stations_error = str(e)

        taxi_stands_updated = False
        taxi_stands_error: str | None = None
        taxi_stands_count: int | None = None
        try:
            taxi_query = f"""[out:json];
(
  node[\"amenity\"=\"taxi\"](around:{RADIUS},{LAT},{LON});
  way[\"amenity\"=\"taxi\"](around:{RADIUS},{LAT},{LON});
  relation[\"amenity\"=\"taxi\"](around:{RADIUS},{LAT},{LON});
);
out center tags;
"""

            response = self.session.post(OVERPASS_URL, data=taxi_query, timeout=60)
            response.raise_for_status()
            overpass_data = response.json()

            stands: list[dict[str, Any]] = []
            for el in overpass_data.get("elements", []) or []:
                if not isinstance(el, dict):
                    continue
                tags = el.get("tags", {})
                if not isinstance(tags, dict):
                    tags = {}

                el_type = el.get("type")
                el_id = el.get("id")
                if el_id is None:
                    continue
                osm_id = f"{el_type}/{el_id}"

                if el_type == "node":
                    lat = el.get("lat")
                    lon = el.get("lon")
                else:
                    center = el.get("center") or {}
                    lat = center.get("lat") if isinstance(center, dict) else None
                    lon = center.get("lon") if isinstance(center, dict) else None

                if lat is None or lon is None:
                    continue
                try:
                    lat_f = float(lat)
                    lon_f = float(lon)
                except Exception:
                    continue

                name = tags.get("name")
                stands.append(
                    {
                        "osm_id": osm_id,
                        "name": str(name) if name is not None else None,
                        "lat": round(lat_f, 6),
                        "lon": round(lon_f, 6),
                        "tags": tags,
                    }
                )

            self.cache.save_taxi_stands(stands)
            taxi_stands_updated = True
            taxi_stands_count = len(stands)
        except Exception as e:
            taxi_stands_error = str(e)

        if to_stdout:
            info_msg = f"⇢ Stops cached: {len(stops_data)}"

            if bikes_updated:
                info_msg += "\n⇢ Nextbike cities cached: YES"
            else:
                info_msg += "\n⇢ Nextbike cities cached: NO"
                if bikes_error:
                    self._warn(f"failed to update Nextbike bike data: {bikes_error}")

            if ticket_machines_updated:
                info_msg += f"\n⇢ Ticket machines cached: {ticket_machines_count or 0}"
            else:
                info_msg += "\n⇢ Ticket machines cached: NO"

            if train_stations_updated:
                info_msg += f"\n⇢ Train stations cached: {train_stations_count or 0}"
            else:
                info_msg += "\n⇢ Train stations cached: NO"

            if taxi_stands_updated:
                info_msg += f"\n⇢ Taxi stands cached: {taxi_stands_count or 0}"
            else:
                info_msg += "\n⇢ Taxi stands cached: NO"

            if (
                train_station_sids_total is not None
                and train_station_sids_found is not None
            ):
                info_msg += f"\n⇢ Train station SIDs found: {train_station_sids_found}/{train_station_sids_total}"

            self._print(Panel(info_msg, title="UPDATE CACHE", border_style="green"))

            if ticket_machines_error:
                self._warn(f"failed to update ticket machines: {ticket_machines_error}")
            if train_stations_error:
                self._warn(f"failed to update train stations: {train_stations_error}")
            if train_station_sids_error:
                self._warn(
                    f"failed to fetch some train station SIDs: {train_station_sids_error}"
                )
            if taxi_stands_error:
                self._warn(f"failed to update taxi stands: {taxi_stands_error}")

        return {
            "updated": "api",
            "stops_count": len(stops_data),
            "bikes_updated": bikes_updated,
            "bikes_error": bikes_error,
            "ticket_machines_updated": ticket_machines_updated,
            "ticket_machines_count": ticket_machines_count,
            "ticket_machines_error": ticket_machines_error,
            "train_stations_updated": train_stations_updated,
            "train_stations_count": train_stations_count,
            "train_stations_error": train_stations_error,
            "train_station_sids_total": train_station_sids_total,
            "train_station_sids_found": train_station_sids_found,
            "train_station_sids_error": train_station_sids_error,
            "taxi_stands_updated": taxi_stands_updated,
            "taxi_stands_count": taxi_stands_count,
            "taxi_stands_error": taxi_stands_error,
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
    # GZM Stops / junctions
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

    def trains(self, name: str, to_stdout: bool = False) -> dict[str, Any]:
        """Lookup a cached train station by name (best-effort closest match).

        Train stations are populated during :meth:`update_api` (Overpass API) and
        stored in the local SQLite cache.

        Args:
            name: Train station name, e.g. ``"Będzin Miasto"``.
            to_stdout: When True, prints a Rich panel with station details.

        Returns:
            JSON-serializable dict with ``query`` and either ``station`` or None.
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
                self._warn("Provide a train station name.")
            return {"error": "invalid_name"}

        station_dict = self.cache.find_train_station_best_match(name)
        station = TrainStation.from_dict(station_dict) if station_dict else None
        if station is None:
            if to_stdout:
                self._warn("No cached train stations found (run update_api first).")
            return {"query": name, "station": None}

        sid = station.sid
        departures_payload: dict[str, Any] | None = None
        if sid:
            departures_payload = try_fetch_portalpasazera_departures(
                self.session, str(sid)
            )

        if to_stdout:
            s_name = station.name
            lat = station.lat
            lon = station.lon
            platforms_qty = station.platforms_qty

            info = f"Station: {s_name}    Building location: ({lat}, {lon})"

            dep_table: Table | None = None
            if departures_payload and isinstance(
                departures_payload.get("departures"), list
            ):
                i = 0
                max_departures = 10
                dep_table = Table(
                    title="Departures (Portal Pasażera)",
                    border_style="deep_sky_blue1",
                    title_justify="left",
                )
                dep_table.add_column("Time")
                dep_table.add_column("Train")
                dep_table.add_column("Destination")
                dep_table.add_column("Via / info")
                dep_table.add_column("Platform")

                for d in departures_payload.get("departures") or []:
                    if not isinstance(d, dict):
                        continue
                    train_label = format_portalpasazera_train_label(d)
                    dep_table.add_row(
                        str(d.get("time") or ""),
                        train_label,
                        str(d.get("destination") or ""),
                        str(d.get("via") or ""),
                        str(d.get("platform") or ""),
                    )
                    i += 1
                    if i >= max_departures:
                        break

            platforms = station.platforms
            if platforms:
                pt = Table(
                    border_style="cyan",
                    title=f"Platforms quantity: {platforms_qty}",
                    title_justify="left",
                )
                pt.add_column("No.")
                pt.add_column("lat")
                pt.add_column("lon")
                for idx, p in enumerate(platforms, start=1):
                    pt.add_row(
                        str(idx),
                        str(p.lat if p.lat is not None else ""),
                        str(p.lon if p.lon is not None else ""),
                    )
                group_items: list[Any] = [info, f"Platforms: {platforms_qty}"]
                if dep_table is not None:
                    group_items.extend(["", dep_table])
                self._print(
                    Panel(
                        Group(*group_items),
                        title=f"Train station: '{name}'",
                        border_style="light_slate_blue",
                    )
                )
            else:
                group_items2: list[Any] = [info]
                if dep_table is not None:
                    group_items2.extend(["", dep_table])
                self._print(
                    Panel(
                        Group(*group_items2),
                        title=f"Train station: '{name}'",
                        border_style="light_slate_blue",
                    )
                )

        return {
            "query": name,
            "station": asdict(station),
            "departures": (departures_payload or {}).get("departures")
            if departures_payload
            else [],
            "departures_station": (departures_payload or {}).get("station")
            if departures_payload
            else None,
            "departures_source": "portalpasazera" if departures_payload else None,
        }

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

        resolved = resolve_junction_details(
            cache=self.cache,
            session=self.session,
            name=name,
            bikes_nearby_meters=self.bikes_nearby_meters,
        )
        if not resolved.variants:
            if to_stdout:
                self._warn(f"Stop not found with name: {name}")
            return {"name": name, "variants": []}

        renderables: list[Any] = []

        nearest_train: dict[str, Any] | None = None
        nearest_train_dist: float | None = None

        best_tm: dict[str, Any] | None = None
        best_tm_dist: float | None = None
        best_taxi: dict[str, Any] | None = None
        best_taxi_dist: float | None = None

        for item in resolved.variants:
            stop = item.get("stop") or {}
            stop_name = stop.get("name")
            stop_id = stop.get("id")
            alt_id = stop.get("alt_id")
            mun = stop.get("municipality")

            lat = stop.get("lat")
            lon = stop.get("lon")
            if lat is not None and lon is not None:
                try:
                    cand = self.cache.find_nearest_train_station(
                        float(lat),
                        float(lon),
                        max_distance_m=300,
                    )
                except Exception:
                    cand = None
                if isinstance(cand, dict) and cand.get("distance_m") is not None:
                    try:
                        cand_dist = float(cand["distance_m"])
                    except Exception:
                        cand_dist = None
                    if cand_dist is not None and (
                        nearest_train_dist is None or cand_dist < nearest_train_dist
                    ):
                        nearest_train_dist = cand_dist
                        nearest_train = cand

            stop_info = item.get("info") or {}
            lines = stop_info.get("lines") or []
            lt = stop_info.get("type") or "N/A"
            lt = "N/A" if isinstance(lt, str) and "br>" in lt else lt

            tm_close = bool(stop.get("ticket_machine"))
            tm_distance_m = stop.get("ticket_machine_distance_m")
            tm_name = stop.get("ticket_machine_name")

            if tm_close:
                cand = {
                    "name": tm_name,
                    "lat": stop.get("ticket_machine_lat"),
                    "lon": stop.get("ticket_machine_lon"),
                    "distance_m": tm_distance_m,
                }
                try:
                    cand_dist = (
                        float(tm_distance_m) if tm_distance_m is not None else None
                    )
                except Exception:
                    cand_dist = None
                if best_tm is None:
                    best_tm = cand
                    best_tm_dist = cand_dist
                elif cand_dist is not None and (
                    best_tm_dist is None or cand_dist < best_tm_dist
                ):
                    best_tm = cand
                    best_tm_dist = cand_dist

            taxi_close = bool(stop.get("taxi_stand"))
            taxi_distance_m = stop.get("taxi_stand_distance_m")
            taxi_name = stop.get("taxi_stand_name")

            if taxi_close:
                cand2 = {
                    "name": taxi_name,
                    "lat": stop.get("taxi_stand_lat"),
                    "lon": stop.get("taxi_stand_lon"),
                    "distance_m": taxi_distance_m,
                }
                try:
                    cand2_dist = (
                        float(taxi_distance_m) if taxi_distance_m is not None else None
                    )
                except Exception:
                    cand2_dist = None
                if best_taxi is None:
                    best_taxi = cand2
                    best_taxi_dist = cand2_dist
                elif cand2_dist is not None and (
                    best_taxi_dist is None or cand2_dist < best_taxi_dist
                ):
                    best_taxi = cand2
                    best_taxi_dist = cand2_dist

            if to_stdout:
                header = f"Stop: {stop_name} | ID={stop_id} | ALT={alt_id} | TYPE={lt} | {mun}"
                renderables.append(
                    Panel(
                        f"Lines: {', '.join(lines) if lines else 'N/A'}",
                        title=header,
                        border_style="deep_sky_blue1",
                    )
                )

        if to_stdout and resolved.nearby_station_occurrences:
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

            rows = sort_nearby_bike_occurrences(
                resolved.nearby_station_occurrences,
                resolved.junction_points,
            )
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

        nearby_train_station: dict[str, Any] | None = None
        nearby_train_departures: list[dict[str, Any]] = []
        if nearest_train is not None:
            nearby_train_station = dict(nearest_train)
            sid = nearby_train_station.get("sid")
            if sid:
                payload = try_fetch_portalpasazera_departures(self.session, str(sid))
                deps = (payload or {}).get("departures")
                if isinstance(deps, list):
                    nearby_train_departures = [d for d in deps if isinstance(d, dict)]

            if to_stdout:
                st_name = str(nearby_train_station.get("name") or "")
                dist_m = nearby_train_station.get("distance_m")
                dist_out = (
                    f"{int(round(float(dist_m)))}m" if dist_m is not None else "?"
                )
                # sid_out = str(nearby_train_station.get("sid") or "")
                header = f"Nearby train station: {st_name} ({dist_out})"

                dep_table: Table | None = None
                if nearby_train_departures:
                    dep_table = Table(
                        title="Departures (Portal Pasażera)",
                        border_style="light_slate_blue",
                        title_justify="left",
                    )
                    dep_table.add_column("Time")
                    dep_table.add_column("Train")
                    dep_table.add_column("Destination")
                    dep_table.add_column("Via / info")
                    dep_table.add_column("Platform")
                    for d in nearby_train_departures[:10]:
                        train_label = format_portalpasazera_train_label(d)
                        dep_table.add_row(
                            str(d.get("time") or ""),
                            train_label,
                            str(d.get("destination") or ""),
                            str(d.get("via") or ""),
                            str(d.get("platform") or ""),
                        )

                renderables.append("")
                if dep_table is None:
                    renderables.append(
                        Panel(
                            "Departures: N/A",
                            title=header,
                            border_style="light_slate_blue",
                        )
                    )
                else:
                    renderables.append(
                        Panel(
                            Group(
                                dep_table,
                            ),
                            title=header,
                            border_style="light_slate_blue",
                        )
                    )

        if to_stdout:
            tm_out = "NO"
            if best_tm is not None:
                try:
                    tm_lat = (
                        float(best_tm.get("lat"))
                        if best_tm.get("lat") is not None
                        else None
                    )
                except Exception:
                    tm_lat = None
                try:
                    tm_lon = (
                        float(best_tm.get("lon"))
                        if best_tm.get("lon") is not None
                        else None
                    )
                except Exception:
                    tm_lon = None
                loc = (
                    f"({tm_lat}, {tm_lon})"
                    if tm_lat is not None and tm_lon is not None
                    else "(N/A)"
                )
                nm = str(best_tm.get("name") or "").strip()
                tm_out = (
                    f"YES - {nm},  Location: {loc}" if nm else f"YES,  Location: {loc}"
                )

            taxi_out = "NO"
            if best_taxi is not None:
                try:
                    tx_lat = (
                        float(best_taxi.get("lat"))
                        if best_taxi.get("lat") is not None
                        else None
                    )
                except Exception:
                    tx_lat = None
                try:
                    tx_lon = (
                        float(best_taxi.get("lon"))
                        if best_taxi.get("lon") is not None
                        else None
                    )
                except Exception:
                    tx_lon = None
                loc2 = (
                    f"({tx_lat}, {tx_lon})"
                    if tx_lat is not None and tx_lon is not None
                    else "(N/A)"
                )
                nm2 = str(best_taxi.get("name") or "").strip()
                taxi_out = (
                    f"YES - {nm2},  Location: {loc2}"
                    if nm2
                    else f"YES,  Location: {loc2}"
                )

            renderables.append("")
            renderables.append(
                Panel(
                    f"Ticket machine: {tm_out}\nTaxi stand: {taxi_out}",
                    title="Others",
                    border_style="green",
                )
            )

        if to_stdout:
            title = f"Junction for '{name}' ({len(resolved.variants)} stops found)."
            self._print(Panel(Group(*renderables), title=title, border_style="cyan"))

        out = resolved.public_result()
        if nearby_train_station is not None:
            out["nearby_train_station"] = nearby_train_station
            out["nearby_train_departures"] = nearby_train_departures
            out["nearby_train_departures_source"] = (
                "portalpasazera" if nearby_train_departures else None
            )
        return out

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

        bike_stations, bike_status = try_load_bike_station_snapshots(self.session)

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
            dt = Table(
                title="Departures", border_style="deep_sky_blue1", title_justify="left"
            )
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
            self._print(
                Panel(Group(*renderables), title=header, border_style="deep_sky_blue1")
            )

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

        summary, error, vid_error = try_resolve_vehicle_trip_summary(
            self.session, did_s
        )
        if error is not None:
            if to_stdout:
                if error.get("error") == "fetch_failed":
                    self._error(
                        f"Error fetching VEHICLE_ALL_DID_URL: {error.get('details', '')}"
                    )
                elif error.get("error") == "unexpected_format":
                    self._error("Unexpected data format (expected dict).")
                elif error.get("error") == "missing_vehicle":
                    self._error("Missing or invalid 'vehicle' item in response.")
            return error

        if vid_error and to_stdout:
            self._warn(f"error fetching VEHICLE_VID_URL: {vid_error}")

        assert summary is not None
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
            payload = load_bike_city_status_full_from_api(self.session, city_id)
        except Exception as e:
            if to_stdout:
                self._error(f"Error fetching Nextbike city status: {e}")
            return {"error": "fetch_failed", "details": str(e)}

        compact = compact_bike_city_status(payload, requested_city_id=city_id)
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
            payload = load_bike_station_status_full_from_api(self.session, sid)
        except Exception as e:
            if to_stdout:
                self._error(f"Error fetching Nextbike station status: {e}")
            return {"error": "fetch_failed", "details": str(e)}

        compact = compact_bike_station_status(payload, requested_station_id=sid)
        if to_stdout:
            self._print_bike_station_status_summary(compact)
        return {"query": {"station_id": sid}, "summary": compact}

    # -----------------------------
    # Internals
    # -----------------------------
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
            Panel(
                f"{city_summary}{bike_stations}",
                border_style="deep_sky_blue1",
                title=title,
            )
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
                border_style="deep_sky_blue1",
                title=f"Bike station: id={station.station_id} | name={station.name}",
            )
        )
