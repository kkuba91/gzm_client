from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from urllib.parse import quote_plus
from typing import Any

import requests

from ..constants import TRAIN_STATION_DEPARTURE_URL, TRAIN_STATION_HTML_SID_FINDING_URL
from .parsers import parse_portalpasazera_departures_json


def portalpasazera_query_name(station_name: str) -> str:
    s = (station_name or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s


def format_portalpasazera_train_label(d: dict[str, Any]) -> str:
    parts = [
        str(d.get("carrier") or "").strip(),
        str(d.get("category") or "").strip(),
        str(d.get("number") or "").strip(),
        str(d.get("name") or "").strip(),
    ]
    label = " ".join(p for p in parts if p)
    return " ".join(label.split()).strip()


def build_train_station_record(
    name: str,
    stations: list[tuple[float, float]],
    stops: list[tuple[float, float]],
) -> dict[str, Any] | None:
    # If station exists → use its coordinates; otherwise average of stops.
    if stations:
        lat, lon = stations[0]
    elif stops:
        lat = sum(s[0] for s in stops) / len(stops)
        lon = sum(s[1] for s in stops) / len(stops)
    else:
        return None

    station = TrainStation.from_dict(
        {
            "name": name,
            "sid": None,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "platforms": [
                {"lat": round(s[0], 6), "lon": round(s[1], 6)} for s in stops
            ],
            "platforms_qty": len(stops),
        }
    )
    return asdict(station) if station else None


def try_fetch_portalpasazera_sid(
    session: requests.Session,
    station_name: str,
    url_template: str = TRAIN_STATION_HTML_SID_FINDING_URL,
) -> str | None:
    """Best-effort resolve Portal Pasażera SID for a station name.

    Uses: https://portalpasazera.pl/KatalogStacji/Index?stacja=<NAME>
    and parses href="/Wyswietlacz?sid=<SID>".
    """
    name = (station_name or "").strip()
    if not name:
        return None

    query_name = portalpasazera_query_name(name)
    url = url_template.format(query_name=quote_plus(query_name))
    try:
        resp = session.get(
            url,
            timeout=12,
            headers={
                "User-Agent": "gzm-client/0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        resp.raise_for_status()
        text = resp.text or ""
    except Exception:
        return None

    m = re.search(r"href=['\"]/Wyswietlacz\?sid=([^'\"]+)['\"]", text)
    if not m:
        return None
    sid = (m.group(1) or "").strip()
    return sid or None


def try_fetch_portalpasazera_departures(
    session: requests.Session,
    sid: str,
    url_template: str = TRAIN_STATION_DEPARTURE_URL,
) -> dict[str, Any] | None:
    sid_s = (sid or "").strip()
    if not sid_s:
        return None

    # Preferred API: JSON board payload
    # https://portalpasazera.pl/Wyswietlacz/PobierzDaneTablicy?s=<SID>&m=0
    # Payload must include `s=<SID>` and `m=0`.
    url = url_template.format(sid_s=sid_s)
    try:
        resp = session.post(
            url,
            timeout=12,
            data={"s": sid_s, "m": "0"},
            headers={
                "User-Agent": "gzm-client/0",
                "Accept": "application/json, text/plain, */*",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None
    parsed = parse_portalpasazera_departures_json(payload)
    return parsed if isinstance(parsed, dict) else None


@dataclass(frozen=True)
class TrainPlatform:
    lat: float | None
    lon: float | None

    @staticmethod
    def from_dict(d: dict[str, Any] | tuple[Any, Any] | None) -> "TrainPlatform" | None:
        if d is None:
            return None
        if isinstance(d, tuple) and len(d) >= 2:
            try:
                return TrainPlatform(lat=float(d[0]), lon=float(d[1]))
            except Exception:
                return TrainPlatform(lat=None, lon=None)
        if not isinstance(d, dict):
            return None

        lat = d.get("lat")
        lon = d.get("lon")
        try:
            lat_f = float(lat) if lat is not None else None
        except Exception:
            lat_f = None
        try:
            lon_f = float(lon) if lon is not None else None
        except Exception:
            lon_f = None
        return TrainPlatform(lat=lat_f, lon=lon_f)


@dataclass(frozen=True)
class TrainStation:
    name: str | None
    sid: str | None
    lat: float | None
    lon: float | None
    platforms_qty: int | None
    platforms: list[TrainPlatform]
    raw: dict[str, Any] | None = None
    match: dict[str, Any] | None = None

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> "TrainStation" | None:
        if d is None:
            return None
        if not isinstance(d, dict):
            return None

        name = d.get("name")
        sid = d.get("sid")

        lat = d.get("lat")
        lon = d.get("lon")
        try:
            lat_f = float(lat) if lat is not None else None
        except Exception:
            lat_f = None
        try:
            lon_f = float(lon) if lon is not None else None
        except Exception:
            lon_f = None

        platforms_qty = d.get("platforms_qty")
        try:
            platforms_qty_i = int(platforms_qty) if platforms_qty is not None else None
        except Exception:
            platforms_qty_i = None

        platforms_in = d.get("platforms")
        platforms: list[TrainPlatform] = []
        if isinstance(platforms_in, list):
            for p in platforms_in:
                pl = TrainPlatform.from_dict(p)  # type: ignore[arg-type]
                if pl is not None:
                    platforms.append(pl)

        raw = d.get("raw")
        if raw is not None and not isinstance(raw, dict):
            raw = None

        match = d.get("match")
        if match is not None and not isinstance(match, dict):
            match = None

        return TrainStation(
            name=str(name) if name is not None else None,
            sid=str(sid) if sid is not None else None,
            lat=lat_f,
            lon=lon_f,
            platforms_qty=platforms_qty_i,
            platforms=platforms,
            raw=raw,
            match=match,
        )
