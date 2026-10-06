"""Unit tests for the pure parsing helpers (no MCP, no HTTP)."""

import pytest

from mbta_mcp.transit import normalize_line, parse_departures, search_stations
from tests.conftest import STATIONS


@pytest.mark.parametrize(
    "line, expected",
    [
        ("Red Line", "Red"),
        ("orange", "Orange"),
        ("Green D", "Green-D"),
        ("green-e branch", "Green-E"),
        ("39", "39"),
        ("CR-Worcester", "CR-Worcester"),
    ],
)
def test_normalize_line(line, expected):
    assert normalize_line(line) == expected


def test_search_requires_every_word():
    assert [s["id"] for s in search_stations(STATIONS["data"], "south station")] == ["place-sstat"]
    assert search_stations(STATIONS["data"], "   ") == []
    assert search_stations(STATIONS["data"], "nowhere") == []


def test_headsign_falls_back_to_prediction_attribute():
    doc = {
        "data": [
            {
                "id": "p",
                "attributes": {"departure_time": "2099-01-01T08:00:00-05:00", "trip_headsign": "Wonderland"},
                "relationships": {"route": {"data": {"id": "Blue"}}, "trip": {"data": None}},
            }
        ]
    }
    [departure] = parse_departures(doc, limit=5)
    assert departure["headsign"] == "Wonderland"
    assert departure["route"] == "Blue"  # no included route data, so the ID is used
