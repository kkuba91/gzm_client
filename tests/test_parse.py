"""Offline tests for mstops-compatible parsing utilities."""

from __future__ import annotations

from gzm_client.transportation.parsers import (
    parse_departures,
    parse_portalpasazera_departures_json,
    parse_stop_info,
)


def test_parse_departures_from_sample_response() -> None:
    # Minimal HTML matching the parser's expected structure.
    sample_html = """
        <div class='departure'>
            <div id='826009655'>
                <span class='linetype-1'></span>
                <div class='line'>M19</div>
                <div class='destination'>Katowice</div>
                <div class='time'>5 min</div>
            </div>
        </div>
        """
    deps = parse_departures(sample_html)
    assert len(deps) >= 1
    assert deps[0]["did"] == "826009655"
    assert deps[0]["line"] == "M19"


def test_parse_stop_info_basic() -> None:
    snippet = "Nowak-Mosty Będzin Arena <br>Stanowisko: 1<br><br>Autobus: <a>27</a>, <a>40</a><br>"
    info = parse_stop_info(snippet)
    assert info["name"] == "Nowak-Mosty Będzin Arena"
    assert info["platform"] == "1"
    assert (info["type"] or "").lower().startswith("autobus")
    assert info["lines"] == ["27", "40"]


def test_parse_portalpasazera_departures_json() -> None:
    payload = {
        "CzyOdjazd": False,
        "Pociagi": [
            {
                "CzyOdwolany": False,
                "KodPrzewoznika": "KS",
                "NazwaPociagu": "S1",
                "NumerPociaguWjazdowy": "40903",
                "NumerPociaguWyjazdowy": "",
                "KategoriaHandlowaWjazdowa": "Os",
                "KategoriaHandlowaWyjazdowa": "",
                "StacjePoczatkowe": [{"Nazwa": "Zawiercie", "CzyLotnisko": False}],
                "StacjeKoncowe": [{"Nazwa": "", "CzyLotnisko": False}],
                "PoprzednieStacjePosrednie": [
                    {"Nazwa": "Łazy", "CzyLotnisko": False},
                    {"Nazwa": "Wiesiółka", "CzyLotnisko": False},
                ],
                "NastepneStacjePosrednie": [],
                "GodzinaPrzyjazdu": "2026-02-03T04:24:30.0000000+01:00",
                "GodzinaOdjazdu": None,
                "PeronTorPrzyjazdowy": "1",
                "PeronTorOdjazdowy": "",
                "TekstUwagPociagu": "",
            }
        ],
    }

    parsed = parse_portalpasazera_departures_json(payload)
    deps = parsed.get("departures")
    assert isinstance(deps, list)
    assert deps and deps[0]["time"] == "04:24"
    assert deps[0]["carrier"] == "KS"
    assert deps[0]["category"] == "Os"
    assert deps[0]["number"] == "40903"
    assert deps[0]["name"] == "S1"
    # Destination can be empty in JSON (arrival board); we fall back to origin.
    assert deps[0]["destination"] == "Zawiercie"
    assert deps[0]["platform"] == "1"
    assert "Łazy" in (deps[0].get("via") or "")
