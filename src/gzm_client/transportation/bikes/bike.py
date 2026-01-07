from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Bike:
    number: Any
    bike_type: Any
    active: Any
    state: Any
    electric_lock: Any
    board_id: Any
    _only_nr: bool = False

    @staticmethod
    def from_dict(d: dict[str, Any] | str) -> "Bike":
        if d is None:
            return None
        if isinstance(d, str):
            return Bike(
                number=d,
                bike_type=None,
                active=None,
                state=None,
                electric_lock=None,
                board_id=None,
                _only_nr=True,
            )
        return Bike(
            number=d.get("number"),
            bike_type=d.get("bike_type"),
            active=d.get("active"),
            state=d.get("state"),
            electric_lock=d.get("electric_lock"),
            board_id=d.get("board_id"),
        )

    def __repr__(self):
        if self._only_nr:
            return f"{self.number}"
        status = "OK" if self.active and self.state == "ok" else "N/A"
        return f" -> number: {self.number},  type: {self.bike_type},  state: {status},  electric lock: {self.electric_lock},  board_id: {self.board_id}"
