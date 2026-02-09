"""HTML parsing utilities and geospatial helpers used by mstops-compatible commands."""

from __future__ import annotations

import html as _html
import math
import re
from typing import Any


def _strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = _html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_portalpasazera_departures(html_text: str) -> dict[str, Any]:
    """Parse Portal Pasażera 'Departures' board table.

    Expects HTML containing a table like: <table class="board depart"> ...
    Returns a JSON-serializable dict with the station name (if found) and
    a list of departure rows.
    """
    text = html_text or ""
    start_re = re.compile(
        r"<table\b[^>]*\bclass\s*=\s*['\"][^'\"]*\bboard\b[^'\"]*\bdepart\b[^'\"]*['\"][^>]*>",
        re.IGNORECASE,
    )
    m = start_re.search(text)
    if not m:
        return {"station": None, "departures": []}

    end_idx = text.lower().find("</table>", m.start())
    if end_idx == -1:
        block = text[m.start() :]
    else:
        block = text[m.start() : end_idx + len("</table>")]

    station_name: str | None = None
    station_m = re.search(
        r"<div\b[^>]*\bclass\s*=\s*['\"][^'\"]*board-station-name[^'\"]*['\"][^>]*>\s*<span>(.*?)</span>",
        block,
        re.IGNORECASE | re.DOTALL,
    )
    if station_m:
        station_name = _strip_tags(station_m.group(1)) or None

    departures: list[dict[str, Any]] = []
    for tr_m in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", block, re.IGNORECASE | re.DOTALL):
        row_html = tr_m.group(1)
        time_m = re.search(
            r"<td\b[^>]*\bclass\s*=\s*['\"][^'\"]*\btime\b[^'\"]*['\"][^>]*>(.*?)</td>",
            row_html,
            re.IGNORECASE | re.DOTALL,
        )
        dest_m = re.search(
            r"<td\b[^>]*\bclass\s*=\s*['\"][^'\"]*\bdest\b[^'\"]*['\"][^>]*>(.*?)</td>",
            row_html,
            re.IGNORECASE | re.DOTALL,
        )
        via_m = re.search(
            r"<td\b[^>]*\bclass\s*=\s*['\"][^'\"]*\bvia\b[^'\"]*['\"][^>]*>(.*?)</td>",
            row_html,
            re.IGNORECASE | re.DOTALL,
        )
        platform_m = re.search(
            r"<td\b[^>]*\bclass\s*=\s*['\"][^'\"]*\bplatform\b[^'\"]*['\"][^>]*>(.*?)</td>",
            row_html,
            re.IGNORECASE | re.DOTALL,
        )
        train_td_m = re.search(
            r"<td\b[^>]*\bclass\s*=\s*['\"][^'\"]*\btrain\b[^'\"]*['\"][^>]*>(.*?)</td>",
            row_html,
            re.IGNORECASE | re.DOTALL,
        )

        time_v = _strip_tags(time_m.group(1)) if time_m else ""
        dest_v = _strip_tags(dest_m.group(1)) if dest_m else ""
        via_v = _strip_tags(via_m.group(1)) if via_m else ""
        platform_v = _strip_tags(platform_m.group(1)) if platform_m else ""

        carrier: str | None = None
        category: str | None = None
        number: str | None = None
        train_name: str | None = None

        if train_td_m:
            train_html = train_td_m.group(1)
            carrier_m = re.search(
                r"<div\b[^>]*\bclass\s*=\s*['\"][^'\"]*carrier-code[^'\"]*['\"][^>]*>(.*?)</div>",
                train_html,
                re.IGNORECASE | re.DOTALL,
            )
            if carrier_m:
                carrier = _strip_tags(carrier_m.group(1)) or None

            category_m = re.search(
                r"<span\b[^>]*\bclass\s*=\s*['\"][^'\"]*train-category[^'\"]*['\"][^>]*>(.*?)</span>",
                train_html,
                re.IGNORECASE | re.DOTALL,
            )
            if category_m:
                category = _strip_tags(category_m.group(1)) or None

            num_m = re.search(
                r"<span\b[^>]*\bclass\s*=\s*['\"][^'\"]*train-num[^'\"]*['\"][^>]*>(.*?)</span>",
                train_html,
                re.IGNORECASE | re.DOTALL,
            )
            if num_m:
                number = _strip_tags(num_m.group(1)) or None

            name_m = re.search(
                r"<div\b[^>]*\bclass\s*=\s*['\"][^'\"]*train-name[^'\"]*['\"][^>]*>(.*?)</div>",
                train_html,
                re.IGNORECASE | re.DOTALL,
            )
            if name_m:
                train_name = _strip_tags(name_m.group(1)) or None

        if not time_v and not dest_v and not platform_v:
            continue

        departures.append(
            {
                "time": time_v or None,
                "carrier": carrier,
                "category": category,
                "number": number,
                "name": train_name,
                "destination": dest_v or None,
                "via": via_v or None,
                "platform": platform_v or None,
            }
        )

    return {"station": station_name, "departures": departures}


def parse_portalpasazera_departures_json(payload: Any) -> dict[str, Any]:
    """Parse Portal Pasażera board JSON from `PobierzDaneTablicy`.

    Endpoint returns a JSON object with a `Pociagi` array. We normalize it to the
    same structure used by the CLI/UI: {station, departures[]}.
    """
    if not isinstance(payload, dict):
        return {"station": None, "departures": []}

    trains = payload.get("Pociagi")
    if not isinstance(trains, list):
        return {"station": None, "departures": []}

    def _extract_hhmm(dt: Any) -> str | None:
        s = str(dt or "").strip()
        if not s:
            return None
        m = re.search(r"T(\d{2}:\d{2})", s)
        return m.group(1) if m else None

    def _first_station_name(items: Any) -> str | None:
        if not isinstance(items, list) or not items:
            return None
        first = items[0]
        if not isinstance(first, dict):
            return None
        name = first.get("Nazwa")
        name_s = str(name or "").strip()
        return name_s or None

    def _stations_list_names(items: Any) -> list[str]:
        if not isinstance(items, list) or not items:
            return []
        out: list[str] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            nm = str(it.get("Nazwa") or "").strip()
            if nm:
                out.append(nm)
        return out

    departures: list[dict[str, Any]] = []
    for tr in trains:
        if not isinstance(tr, dict):
            continue

        carrier = tr.get("KodPrzewoznika")
        train_name = tr.get("NazwaPociagu")
        number = tr.get("NumerPociaguWyjazdowy") or tr.get("NumerPociaguWjazdowy")
        category = tr.get("KategoriaHandlowaWyjazdowa") or tr.get(
            "KategoriaHandlowaWjazdowa"
        )

        time_val = _extract_hhmm(tr.get("GodzinaOdjazdu") or tr.get("GodzinaPrzyjazdu"))
        platform = (
            str(
                (tr.get("PeronTorOdjazdowy") or tr.get("PeronTorPrzyjazdowy") or "")
            ).strip()
            or None
        )

        # Prefer destination (end station); fall back to origin when end is empty.
        destination = _first_station_name(tr.get("StacjeKoncowe"))
        if not destination:
            destination = _first_station_name(tr.get("StacjePoczatkowe"))

        is_departure_board = bool(payload.get("CzyOdjazd"))
        via_list = (
            _stations_list_names(tr.get("NastepneStacjePosrednie"))
            if is_departure_board
            else _stations_list_names(tr.get("PoprzednieStacjePosrednie"))
        )
        via = ", ".join(via_list).strip() or None

        notes = str(tr.get("TekstUwagPociagu") or "").strip()
        if notes:
            via = (f"{via} | {notes}" if via else notes) or None

        departures.append(
            {
                "time": time_val,
                "carrier": str(carrier).strip() if carrier is not None else None,
                "category": str(category).strip() if category is not None else None,
                "number": str(number).strip() if number is not None else None,
                "name": str(train_name).strip() if train_name is not None else None,
                "destination": destination,
                "via": via,
                "platform": platform,
                "cancelled": bool(tr.get("CzyOdwolany"))
                if tr.get("CzyOdwolany") is not None
                else None,
            }
        )

    return {"station": None, "departures": departures}


def parse_bike_stations_locations_payload(payload: Any) -> list[dict[str, Any]]:
    """Parse Nextbike GBFS station_information payload.

    Expected structure: {"data": {"stations": [...]}}
    Returns the stations list.
    """
    if not isinstance(payload, dict):
        raise ValueError("Unexpected station_information format (expected dict).")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Missing or invalid 'data' field in station_information.")
    stations = data.get("stations")
    if not isinstance(stations, list):
        raise ValueError("Missing or invalid 'stations' field in station_information.")
    return stations


def parse_bike_stations_status_payload(payload: Any) -> dict[str, dict[str, Any]]:
    """Parse Nextbike GBFS station_status payload.

    Expected structure: {"data": {"stations": [...]}}
    Returns a dict keyed by station_id.
    """
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


def extract_balanced_div(
    html_text: str, start_index: int
) -> tuple[int | None, str | None]:
    """Return (end_index, substring) for a balanced <div>..</div> block."""
    counter = 0
    iterator = re.finditer(r"<div\b|</div>", html_text[start_index:], re.IGNORECASE)
    for m in iterator:
        token = m.group(0).lower()
        if token.startswith("<div"):
            counter += 1
        else:
            counter -= 1
        if counter == 0:
            end_pos = start_index + m.end()
            return end_pos, html_text[start_index:end_pos]
    return None, None


def parse_departures(html_text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    start_pattern = re.compile(
        r"<div\b[^>]*\bclass\s*=\s*['\"][^'\"]*\bdeparture\b[^'\"]*['\"][^>]*>",
        re.IGNORECASE,
    )

    for m in start_pattern.finditer(html_text or ""):
        start = m.start()
        _, block = extract_balanced_div(html_text, start)
        if not block:
            block = (html_text or "")[start : start + 2000]

        id_attr_re = re.compile(
            r"<div\b[^>]*\bid\s*=\s*['\"]?(\d+)['\"]?[^>]*>", re.IGNORECASE
        )
        did_m = id_attr_re.search(block)
        did = did_m.group(1) if did_m else None

        lt_re = re.compile(
            r"class\s*=\s*['\"][^'\"]*linetype-(\d+)[^'\"]*['\"]", re.IGNORECASE
        )
        lt_m = lt_re.search(block)
        line_type = lt_m.group(1) if lt_m else None

        line_re = re.compile(
            r"<div\b[^>]*\bclass\s*=\s*['\"]line['\"][^>]*>(.*?)</div>",
            re.IGNORECASE | re.DOTALL,
        )
        line_m = line_re.search(block)
        line = line_m.group(1).strip() if line_m else None

        dest_re = re.compile(
            r"<div\b[^>]*\bclass\s*=\s*['\"]destination['\"][^>]*>(.*?)</div>",
            re.IGNORECASE | re.DOTALL,
        )
        dest_m = dest_re.search(block)
        dest = dest_m.group(1).strip() if dest_m else None

        time_re = re.compile(
            r"<div\b[^>]*\bclass\s*=\s*['\"]time['\"][^>]*>(.*?)</div>",
            re.IGNORECASE | re.DOTALL,
        )
        time_m = time_re.search(block)
        time_val = time_m.group(1).strip() if time_m else None

        if line:
            line = _html.unescape(re.sub(r"\s+", " ", line)).strip()
        if dest:
            dest = _html.unescape(re.sub(r"\s+", " ", dest)).strip()
        if time_val:
            time_val = _html.unescape(re.sub(r"\s+", " ", time_val)).strip()

        results.append(
            {
                "did": did,
                "line_type": line_type,
                "line": line,
                "destination": dest,
                "time": time_val,
            }
        )

    return results


def parse_stop_info(html_text: str) -> dict[str, Any]:
    def _normalize_text(value: str) -> str:
        value = _html.unescape(value)
        value = re.sub(r"\s+", " ", value).strip()
        if re.search(r"[ÃÄÅÂ]", value):
            try:
                candidate = value.encode("latin-1").decode("utf-8")
                if candidate and "\ufffd" not in candidate:
                    value = candidate
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        return value

    if not html_text:
        return {"name": None, "platform": None, "type": None, "lines": []}

    text = html_text.strip()
    name_m = re.search(r"^\s*(.*?)\s*<br\s*/?>", text, re.IGNORECASE | re.DOTALL)
    name = _normalize_text(name_m.group(1)) if name_m else None

    plat_m = re.search(r"Stanowisko\s*:\s*([^<\r\n]+)", text, re.IGNORECASE)
    platform = _normalize_text(plat_m.group(1)) if plat_m else None

    type_val = None
    lines: list[str] = []
    tail = None

    type_block_m = re.search(
        r"(?:<br\s*/?>\s*){2,}\s*([^:<]+?)\s*:\s*(.*)$",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if type_block_m:
        type_val = _normalize_text(type_block_m.group(1))
        tail = type_block_m.group(2)
    else:
        type_fallback_m = re.search(
            r"\b([^:<]+?)\s*:\s*(.*)$", text, re.IGNORECASE | re.DOTALL
        )
        if type_fallback_m:
            type_val = _normalize_text(type_fallback_m.group(1))
            tail = type_fallback_m.group(2)

    if tail:
        for raw in re.findall(r"<a\b[^>]*>(.*?)</a>", tail, re.IGNORECASE | re.DOTALL):
            line = _normalize_text(raw)
            if line:
                lines.append(line)

    return {"name": name, "platform": platform, "type": type_val, "lines": lines}


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


def find_nearby_bike_stations(
    lat: float,
    lon: float,
    stations: list[dict[str, Any]],
    status_by_id: dict[str, dict[str, Any]],
    max_distance_m: int,
    region_id: str | None = None,
) -> list[dict[str, Any]]:
    if lat is None or lon is None:
        return []

    lat_f = float(lat)
    lon_f = float(lon)
    dlat = max_distance_m / 111320.0
    denom = 111320.0 * max(0.2, math.cos(math.radians(lat_f)))
    dlon = max_distance_m / denom

    results: list[dict[str, Any]] = []
    for s in stations:
        if not isinstance(s, dict):
            continue
        if region_id is not None and str(s.get("region_id")) != str(region_id):
            continue
        slat = s.get("lat")
        slon = s.get("lon")
        if slat is None or slon is None:
            continue
        slat_f = float(slat)
        slon_f = float(slon)
        if abs(slat_f - lat_f) > dlat or abs(slon_f - lon_f) > dlon:
            continue
        dist_m = _haversine_m(lat_f, lon_f, slat_f, slon_f)
        if dist_m <= max_distance_m:
            sid = str(s.get("station_id")) if s.get("station_id") is not None else ""
            st = status_by_id.get(sid, {}) if sid else {}
            results.append(
                {
                    "station_id": sid,
                    "name": s.get("name"),
                    "short_name": s.get("short_name"),
                    "capacity": s.get("capacity"),
                    "distance_m": dist_m,
                    "bikes_available": st.get("num_bikes_available"),
                    "docks_available": st.get("num_docks_available"),
                    "position": [slat_f, slon_f],
                }
            )
    results.sort(key=lambda x: x.get("distance_m", 10**9))
    return results
