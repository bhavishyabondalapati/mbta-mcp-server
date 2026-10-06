"""Shared fixtures. Every test runs offline: respx intercepts all httpx requests."""

from datetime import datetime, timedelta, timezone

import pytest
import respx

from mbta_mcp import api, server

BASE = "https://api-v3.mbta.com"


@pytest.fixture(autouse=True)
def fresh_client(monkeypatch):
    """Give each test its own client (empty cache, no API key) and skip real sleeps."""
    monkeypatch.setattr(server, "client", api.MBTAClient(api_key=""))

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(api.asyncio, "sleep", no_sleep)


@pytest.fixture
def mbta():
    """A respx router; any request that is not mocked fails the test."""
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


def station(stop_id, name, municipality="Boston"):
    return {
        "id": stop_id,
        "type": "stop",
        "attributes": {"name": name, "municipality": municipality, "vehicle_type": None},
    }


STATIONS = {
    "data": [
        station("place-pktrm", "Park Street"),
        station("place-harsq", "Harvard", "Cambridge"),
        station("place-hymnl", "Hynes Convention Center"),
        station("place-sstat", "South Station"),
        station("place-north", "North Station"),
    ]
}


def iso_in(minutes):
    """An ISO timestamp `minutes` from now, in Boston's UTC-4 offset like the real API."""
    eastern = timezone(timedelta(hours=-4))
    return (datetime.now(eastern) + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def prediction(pid, route, trip, departure, headsign_fallback=None):
    return {
        "id": pid,
        "type": "prediction",
        "attributes": {
            "arrival_time": departure,
            "departure_time": departure,
            "status": None,
            "trip_headsign": headsign_fallback,
        },
        "relationships": {
            "route": {"data": {"id": route, "type": "route"}},
            "trip": {"data": {"id": trip, "type": "trip"}},
        },
    }


def predictions_doc():
    return {
        "data": [
            prediction("p3", "Green-B", "t3", iso_in(9)),
            prediction("p1", "Red", "t1", iso_in(2)),
            prediction("p-arrival-only", "Red", "t9", None),  # train ending its trip here
            prediction("p-past", "Red", "t8", iso_in(-5)),
            prediction("p2", "Red", "t2", iso_in(5)),
        ],
        "included": [
            {"type": "route", "id": "Red", "attributes": {"long_name": "Red Line", "short_name": "", "type": 1}},
            {"type": "route", "id": "Green-B", "attributes": {"long_name": "Green Line B", "short_name": "B", "type": 0}},
            {"type": "trip", "id": "t1", "attributes": {"headsign": "Ashmont"}},
            {"type": "trip", "id": "t2", "attributes": {"headsign": "Alewife"}},
            {"type": "trip", "id": "t3", "attributes": {"headsign": "Boston College"}},
        ],
    }


def alerts_doc():
    return {
        "data": [
            {
                "id": "minor",
                "type": "alert",
                "attributes": {
                    "effect": "STATION_ISSUE",
                    "severity": 1,
                    "service_effect": "Station issue at Savin Hill",
                    "header": "A staircase is out of service.",
                    "lifecycle": "ONGOING",
                    "timeframe": "ongoing",
                    "url": None,
                },
            },
            {
                "id": "major",
                "type": "alert",
                "attributes": {
                    "effect": "DELAY",
                    "severity": 7,
                    "service_effect": "Red Line delay",
                    "header": "Delays of up to 20 minutes due to a disabled train.",
                    "lifecycle": "NEW",
                    "timeframe": None,
                    "url": None,
                },
            },
        ]
    }
