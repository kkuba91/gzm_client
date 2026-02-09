from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import requests

from ..constants import STOP_URL


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


def fetch_stop_snippet(
    session: requests.Session,
    stop_id: str | int,
    url_template: str = STOP_URL,
    timeout: float = 8,
) -> str:
    url = url_template.format(stop_id)
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


async def fetch_stop_snippets_async(
    stop_ids: list[str],
    url_template: str = STOP_URL,
    concurrency: int = 10,
    timeout_s: float = 8.0,
) -> dict[str, str]:
    """Fetch many stop HTML snippets concurrently (best-effort)."""
    out: dict[str, str] = {}
    if not stop_ids:
        return out

    sem = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(timeout_s)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:

        async def one(stop_id: str) -> tuple[str, str]:
            async with sem:
                r = await client.get(url_template.format(stop_id))
                r.raise_for_status()
                return stop_id, r.text

        results = await asyncio.gather(
            *(one(stop_id) for stop_id in stop_ids), return_exceptions=True
        )
        for item in results:
            if isinstance(item, Exception):
                continue
            sid, text = item
            out[str(sid)] = text
    return out
