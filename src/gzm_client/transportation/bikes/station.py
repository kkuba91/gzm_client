from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bike import Bike


@dataclass(frozen=True)
class BikeStation:
    station_id: str
    name: Any
    short_name: Any
    position: list[float]
    capacity: Any
    bikes_available: Any
    docks_available: Any
    bike_list: list[Any] = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "BikeStation":
        return BikeStation(
            station_id=str(d.get("station_id") or d.get("uid") or ""),
            name=d.get("name") or d.get("number"),
            short_name=d.get("short_name"),
            position=d.get("position")
            or d.get("pos")
            or [d.get("lat"), d.get("lon")]
            or [0.0, 0.0],
            capacity=d.get("capacity") or d.get("rack_size"),
            bikes_available=d.get("bikes_available") or d.get("available"),
            docks_available=d.get("docks_available") or d.get("free_racks"),
            bike_list=[
                Bike.from_dict(bike_dict) for bike_dict in d.get("bike_list", [])
            ]
            if d.get("bike_list")
            else [],
        )

    def __repr__(self):
        prefix = "-> "
        if any(not bike.bike_type for bike in self.bike_list):
            bike_list = "[" + ", ".join(str(bike) for bike in self.bike_list) + "]"
        elif not self.bike_list:
            bike_list = "[]"
        else:
            prefix = "Station | "
            bike_list = "\n" + "\n".join(repr(bike) for bike in self.bike_list)
        return (
            f"{prefix}id: {self.station_id},  name: {self.name or self.short_name},  pos: {self.position},  capacity: {self.capacity},  available: {self.bikes_available}"
            f"\n Available bikes: {bike_list}"
        )


@dataclass(frozen=True)
class BikeStationNearby(BikeStation):
    distance_m: float = 0.0

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "BikeStationNearby":
        return BikeStationNearby(
            station_id=str(d.get("station_id") or d.get("uid") or ""),
            name=d.get("name"),
            short_name=d.get("short_name"),
            position=d.get("position") or [d.get("lat"), d.get("lon")] or [0.0, 0.0],
            capacity=d.get("capacity"),
            distance_m=float(d.get("distance_m") or 0.0),
            bikes_available=d.get("bikes_available"),
            docks_available=d.get("docks_available"),
        )
