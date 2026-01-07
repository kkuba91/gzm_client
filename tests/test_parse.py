"""Offline tests for mstops-compatible parsing utilities."""

from __future__ import annotations

from gzm_client.transportation.parsers import parse_departures, parse_stop_info


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
