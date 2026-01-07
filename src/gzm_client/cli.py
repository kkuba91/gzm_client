"""CLI for the GZM transport client.

Commands are aligned with mstops.py for a smooth migration.
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import GzmClient


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gzm-client")
    p.add_argument(
        "--db",
        default=None,
        help="SQLite database path (default: stops.db in current working dir)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output (disables rich stdout rendering)",
    )

    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser(
        "update_api", help="Fetches data from the API and updates the database."
    )

    p_upf = sub.add_parser(
        "update_file",
        help="Loads data from a local JSON file and updates the database.",
    )
    p_upf.add_argument("path")

    p_list = sub.add_parser("list", help="Lists stops for the given city.")
    p_list.add_argument("city")

    p_j = sub.add_parser(
        "junction",
        help="Prints all variants for a junction stop, including stop IDs and served lines.",
    )
    p_j.add_argument("name", nargs=argparse.REMAINDER)

    p_stop = sub.add_parser("stop", help="Prints upcoming departures from the stop.")
    p_stop.add_argument("stop_id")

    p_go = sub.add_parser(
        "go",
        help="Fetches trip data by did (vehicle-all), enriches it by vid and prints a summary.",
    )
    p_go.add_argument("did")

    p_b = sub.add_parser("bikes", help="Nextbike (GZM bikes) related commands.")
    sub_b = p_b.add_subparsers(dest="bikes_cmd", required=True)

    p_bc = sub_b.add_parser(
        "city", help="Print Nextbike status for a city (resolved via cached city list)."
    )
    p_bc.add_argument("city_prefix", nargs=argparse.REMAINDER)

    p_bs = sub_b.add_parser(
        "station", help="Print Nextbike status for a station/place id."
    )
    p_bs.add_argument("station_id")

    return p


def _emit(result: object, as_json: bool) -> None:
    if not as_json:
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    ns = _build_parser().parse_args(argv)
    client = GzmClient(db_path=ns.db)
    to_stdout = not bool(ns.json)

    if ns.cmd == "update_api":
        res = client.update_api(to_stdout=to_stdout)
        _emit(res, ns.json)
        return 0

    if ns.cmd == "update_file":
        res = client.update_file(ns.path, to_stdout=to_stdout)
        _emit(res, ns.json)
        return 0

    if ns.cmd == "list":
        res = client.list_by_municipality(ns.city, to_stdout=to_stdout)
        _emit(res, ns.json)
        return 0

    if ns.cmd == "junction":
        name = " ".join(ns.name).strip()
        res = client.junction(name, to_stdout=to_stdout)
        _emit(res, ns.json)
        return 0

    if ns.cmd == "stop":
        res = client.stop_departures(ns.stop_id, to_stdout=to_stdout)
        _emit(res, ns.json)
        return 0

    if ns.cmd == "go":
        res = client.go_for_did(ns.did, to_stdout=to_stdout)
        _emit(res, ns.json)
        return 0

    if ns.cmd == "bikes":
        if ns.bikes_cmd == "city":
            prefix = " ".join(ns.city_prefix).strip()
            res = client.bikes_city(prefix, to_stdout=to_stdout)
            _emit(res, ns.json)
            return 0
        if ns.bikes_cmd == "station":
            res = client.bikes_station(ns.station_id, to_stdout=to_stdout)
            _emit(res, ns.json)
            return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
