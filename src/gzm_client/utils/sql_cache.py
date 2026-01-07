"""SQLite cache used by mstops-compatible commands."""

from __future__ import annotations

import json
import os
import sqlite3
import math
from typing import Any


class StopsSqlCache:
    """A minimal SQLite cache mirroring mstops.py schema and queries."""

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

    def __init__(self, db_path: str = "stops.db") -> None:
        self.db_path = db_path

    def exists(self) -> bool:
        return os.path.exists(self.db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
				CREATE TABLE IF NOT EXISTS stops (
					id TEXT PRIMARY KEY,
					alt_id TEXT,
					name TEXT,
					address TEXT,
					lat REAL,
					lon REAL,
					linetype TEXT,
					municipality TEXT,
					platform TEXT,
					raw_json TEXT
				)
				"""
            )
            cur.execute(
                """
				CREATE TABLE IF NOT EXISTS bike_cities (
					region_id TEXT PRIMARY KEY,
					name TEXT,
					last_updated INTEGER,
					ttl INTEGER,
					raw_json TEXT
				)
				"""
            )
            cur.execute(
                """
				CREATE TABLE IF NOT EXISTS ticket_machines (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					lat REAL,
					lon REAL,
					name TEXT,
					kind TEXT,
					raw_json TEXT
				)
				"""
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ticket_machines_lat_lon ON ticket_machines(lat, lon)"
            )
            conn.commit()
        finally:
            conn.close()

    def save_ticket_machines(self, machines: list[list[Any]]) -> None:
        """Persist ticket machine locations.

        Expected payload: [[lat, lon, name, kind], ...]
        """
        self.init_db()
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM ticket_machines")
            for m in machines:
                if not isinstance(m, (list, tuple)) or len(m) < 4:
                    continue
                lat, lon, name, kind = m[0], m[1], m[2], m[3]
                if lat is None or lon is None:
                    continue
                try:
                    lat_f = float(lat)
                    lon_f = float(lon)
                except Exception:
                    continue
                cur.execute(
                    """
					INSERT INTO ticket_machines (lat, lon, name, kind, raw_json)
					VALUES (?, ?, ?, ?, ?)
					""",
                    (
                        lat_f,
                        lon_f,
                        str(name) if name is not None else None,
                        str(kind) if kind is not None else None,
                        json.dumps(m, ensure_ascii=False),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def find_nearest_ticket_machine(
        self,
        lat: float,
        lon: float,
        max_distance_m: int = 300,
    ) -> dict[str, Any] | None:
        if not self.exists():
            return None
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except Exception:
            return None
        dlat = max_distance_m / 111320.0
        denom = 111320.0 * max(0.2, math.cos(math.radians(lat_f)))
        dlon = max_distance_m / denom
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
				SELECT lat, lon, name, kind
				FROM ticket_machines
				WHERE lat BETWEEN ? AND ?
				  AND lon BETWEEN ? AND ?
				""",
                (lat_f - dlat, lat_f + dlat, lon_f - dlon, lon_f + dlon),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        best: dict[str, Any] | None = None
        best_dist: float | None = None
        for r in rows or []:
            try:
                mlat = float(r[0])
                mlon = float(r[1])
            except Exception:
                continue
            dist = self._haversine_m(lat_f, lon_f, mlat, mlon)
            if dist > float(max_distance_m):
                continue
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = {
                    "lat": mlat,
                    "lon": mlon,
                    "name": r[2],
                    "kind": r[3],
                    "distance_m": dist,
                }
        return best

    def save_stops(self, data: list[dict[str, Any]]) -> None:
        self.init_db()
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM stops")
            for item in data:
                cur.execute(
                    """
					INSERT INTO stops (
						id, alt_id, name, address, lat, lon,
						linetype, municipality, platform, raw_json
					) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
					""",
                    (
                        str(item.get("id")),
                        item.get("alt_id"),
                        item.get("name"),
                        item.get("address"),
                        item.get("lat"),
                        item.get("lon"),
                        item.get("linetype"),
                        item.get("municipality"),
                        item.get("platform"),
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def save_bike_cities(
        self,
        regions: list[dict[str, Any]],
        last_updated: int | None = None,
        ttl: int | None = None,
    ) -> None:
        self.init_db()
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM bike_cities")
            for region in regions:
                if not isinstance(region, dict):
                    continue
                region_id = region.get("region_id")
                name = region.get("name")
                if region_id is None or name is None:
                    continue
                cur.execute(
                    """
					INSERT INTO bike_cities (region_id, name, last_updated, ttl, raw_json)
					VALUES (?, ?, ?, ?, ?)
					""",
                    (
                        str(region_id),
                        str(name),
                        int(last_updated) if isinstance(last_updated, int) else None,
                        int(ttl) if isinstance(ttl, int) else None,
                        json.dumps(region, ensure_ascii=False),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def list_grouped_by_municipality(self, city: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
				SELECT id, alt_id, name, lat, lon
				FROM stops
				WHERE LOWER(municipality) = LOWER(?)
				ORDER BY name
				""",
                (str(city).upper(),),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            return []

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            stop_name = row["name"]
            if stop_name in grouped:
                grouped[stop_name]["ids"].append(row["id"])
                grouped[stop_name]["alts"].append(row["alt_id"])
                grouped[stop_name]["coords"].append((row["lat"], row["lon"]))
            else:
                grouped[stop_name] = {
                    "name": stop_name,
                    "ids": [row["id"]],
                    "alts": [row["alt_id"]],
                    "coords": [(row["lat"], row["lon"])],
                }
        return list(grouped.values())

    def find_stop_variants_by_name(self, name: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
				SELECT id, alt_id, name, municipality, lat, lon
				FROM stops
				WHERE LOWER(name) = LOWER(?)
				ORDER BY alt_id
				""",
                (name,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def find_stop_by_id(self, stop_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
				SELECT id, alt_id, name, municipality, lat, lon
				FROM stops
				WHERE id = ?
				ORDER BY name
				""",
                (stop_id,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        return dict(rows[-1]) if rows else None

    def find_bike_city_ids_by_name_part(self, name_part: str) -> list[tuple[str, str]]:
        if not self.exists():
            return []
        part = (name_part or "").strip()
        if not part:
            return []
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
				SELECT region_id, name
				FROM bike_cities
				WHERE LOWER(name) LIKE '%' || LOWER(?) || '%'
				ORDER BY name
				""",
                (part,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        return [(str(r[0]), str(r[1])) for r in rows]

    def find_bike_city_ids_by_name_prefix(
        self, name_prefix: str
    ) -> list[tuple[str, str]]:
        if not self.exists():
            return []
        prefix = (name_prefix or "").strip()
        if not prefix:
            return []
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
				SELECT region_id, name
				FROM bike_cities
				WHERE LOWER(name) LIKE LOWER(?) || '%'
				ORDER BY name
				""",
                (prefix,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        return [(str(r[0]), str(r[1])) for r in rows]

    def resolve_bike_city_id_by_prefix(
        self, name_prefix: str
    ) -> tuple[str | None, str | None]:
        matches = self.find_bike_city_ids_by_name_prefix(name_prefix)
        if len(matches) == 1:
            return matches[0][0], matches[0][1]
        return None, None

    def find_unambiguous_bike_city_id_by_name_part(self, name_part: str) -> str | None:
        matches = self.find_bike_city_ids_by_name_part(name_part)
        if len(matches) == 1:
            return matches[0][0]
        return None
