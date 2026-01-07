"""Junction-related models.

In mstops-compatible operations a junction is represented by a stop name with
multiple variants (different ids/platforms).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JunctionQuery:
    name: str
