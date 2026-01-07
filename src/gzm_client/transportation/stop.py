from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Departure:
    did: str | None
    line_type: str | None
    line: str | None
    destination: str | None
    time: str | None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Departure":
        return Departure(
            did=d.get("did"),
            line_type=d.get("line_type"),
            line=d.get("line"),
            destination=d.get("destination"),
            time=d.get("time"),
        )
