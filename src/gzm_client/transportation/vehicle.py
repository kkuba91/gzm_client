from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
