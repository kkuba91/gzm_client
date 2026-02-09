from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from ..constants import VEHICLE_ALL_DID_URL, VEHICLE_VID_URL


@dataclass
class VehicleTripSummary:
    did: str
    vehicle_id: str | None
    vehicle_type: Any
    line_out: str
    route_name: Any
    next_stop: dict[str, Any] | None
    lat: Any
    lon: Any

    @staticmethod
    def from_vehicle_all_payload(
        did: str, payload: dict[str, Any]
    ) -> "VehicleTripSummary":
        vehicle = (
            payload.get("vehicle") if isinstance(payload.get("vehicle"), dict) else {}
        )
        line_obj = payload.get("line") if isinstance(payload.get("line"), dict) else {}

        line_val = line_obj.get("line")
        line_label = vehicle.get("lineLabel")
        if line_val and line_label and str(line_val) != str(line_label):
            line_out = f"{line_val}/{line_label}"
        else:
            line_out = line_val or line_label or ""

        next_stop = vehicle.get("nextStop")
        next_stop_out = None
        if isinstance(next_stop, dict):
            next_stop_out = {k: v for k, v in next_stop.items() if k != "id"}

        return VehicleTripSummary(
            did=did,
            vehicle_id=str(vehicle.get("id"))
            if vehicle.get("id") is not None
            else None,
            vehicle_type=vehicle.get("type"),
            line_out=str(line_out),
            route_name=line_obj.get("name"),
            next_stop=next_stop_out,
            lat=vehicle.get("lat"),
            lon=vehicle.get("lon"),
        )


def try_resolve_vehicle_trip_summary(
    session: requests.Session,
    did: str,
    url_all_template: str = VEHICLE_ALL_DID_URL,
    url_vid_template: str = VEHICLE_VID_URL,
) -> tuple[VehicleTripSummary | None, dict[str, Any] | None, str | None]:
    """Resolve VehicleTripSummary by DID using live API calls.

    Returns:
    - (summary, None, vid_error) on success
    - (None, error_dict, None) on a hard error

    The error_dict values are aligned with the mstops-compatible client behavior.
    """
    did_s = str(did).strip()
    url_all = url_all_template.format(did_s)
    try:
        resp = session.get(url_all, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return None, {"error": "fetch_failed", "details": str(e)}, None

    if not isinstance(data, dict):
        return None, {"error": "unexpected_format"}, None

    vehicle = data.get("vehicle")
    if not isinstance(vehicle, dict):
        return None, {"error": "missing_vehicle"}, None

    vid_error: str | None = None
    vehicle_id = vehicle.get("id")
    if vehicle_id:
        url_vid = url_vid_template.format(vehicle_id)
        try:
            resp2 = session.get(url_vid, timeout=10)
            resp2.raise_for_status()
            upd = resp2.json()
            if isinstance(upd, list) and upd and isinstance(upd[0], dict):
                vehicle.update(upd[0])
        except Exception as e:
            vid_error = str(e)

    summary = VehicleTripSummary.from_vehicle_all_payload(did_s, data)
    return summary, None, vid_error
