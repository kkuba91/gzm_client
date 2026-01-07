"""HTML parsing utilities and geospatial helpers used by mstops-compatible commands."""

from __future__ import annotations

import html as _html
import math
import re
from typing import Any


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
