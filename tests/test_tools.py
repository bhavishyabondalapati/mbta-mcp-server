"""Tests for the three MCP tools, called through a real in-process MCP client."""

import json

import httpx
import pytest
from mcp import Client

from mbta_mcp.server import mcp
from tests.conftest import STATIONS, alerts_doc, predictions_doc


async def call(name, arguments):
    """Call a tool the same way Claude Desktop would, and return the result."""
    async with Client(mcp) as client:
        return await client.call_tool(name, arguments)


def payload(result):
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


async def test_server_lists_all_three_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools.tools} == {"search_stops", "next_departures", "service_alerts"}


async def test_search_stops_ranks_and_caches(mbta):
    route = mbta.get("/stops").respond(json=STATIONS)

    result = payload(await call("search_stops", {"query": "station"}))
    assert [s["id"] for s in result["stops"]] == ["place-north", "place-sstat"]

    result = payload(await call("search_stops", {"query": "PARK st"}))
    assert result["stops"] == [{"id": "place-pktrm", "name": "Park Street", "municipality": "Boston"}]

    assert route.call_count == 1  # second search used the cached station list


async def test_next_departures_by_station_name(mbta):
    mbta.get("/stops").respond(json=STATIONS)
    route = mbta.get("/predictions").respond(json=predictions_doc())

    result = payload(await call("next_departures", {"stop": "park street", "limit": 5}))

    assert route.calls.last.request.url.params["filter[stop]"] == "place-pktrm"
    assert result["stop_name"] == "Park Street"
    # Sorted by time; arrival-only and already-departed predictions are dropped.
    assert [d["headsign"] for d in result["departures"]] == ["Ashmont", "Alewife", "Boston College"]
    first = result["departures"][0]
    assert first["route"] == "Red Line" and first["mode"] == "Subway"
    assert 0 <= first["minutes_away"] <= 2


async def test_next_departures_ambiguous_name_asks_for_id(mbta):
    mbta.get("/stops").respond(json=STATIONS)

    result = await call("next_departures", {"stop": "station"})

    assert result.is_error
    assert "place-north" in result.content[0].text and "place-sstat" in result.content[0].text


async def test_service_alerts_normalizes_line_and_sorts_by_severity(mbta):
    route = mbta.get("/alerts").respond(json=alerts_doc())

    result = payload(await call("service_alerts", {"line": "Red Line"}))

    assert route.calls.last.request.url.params["filter[route]"] == "Red"
    assert [a["id"] for a in result["alerts"]] == ["major", "minor"]


async def test_green_line_expands_to_all_branches(mbta):
    route = mbta.get("/alerts").respond(json={"data": []})

    result = payload(await call("service_alerts", {"line": "green"}))

    assert route.calls.last.request.url.params["filter[route]"] == "Green-B,Green-C,Green-D,Green-E"
    assert result["count"] == 0


async def test_short_rate_limit_is_retried(mbta):
    mbta.get("/alerts").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "1"}),
            httpx.Response(200, json=alerts_doc()),
        ]
    )

    result = payload(await call("service_alerts", {"line": "Red"}))
    assert result["count"] == 2


async def test_long_rate_limit_returns_clean_error(mbta):
    mbta.get("/alerts").respond(429, headers={"retry-after": "45"})

    result = await call("service_alerts", {"line": "Red"})

    assert result.is_error
    assert "rate limit" in result.content[0].text
    assert "45 seconds" in result.content[0].text


@pytest.mark.parametrize(
    "responses, expected",
    [
        ([httpx.Response(503), httpx.Response(503)], "HTTP 503"),
        ([httpx.TimeoutException("slow"), httpx.TimeoutException("slow")], "timed out"),
        ([httpx.Response(400, json={"errors": [{"detail": "Bad filter"}]})], "Bad filter"),
    ],
)
async def test_api_failures_become_tool_errors(mbta, responses, expected):
    mbta.get("/alerts").mock(side_effect=responses)

    result = await call("service_alerts", {"line": "Red"})

    assert result.is_error
    assert expected in result.content[0].text


async def test_server_error_then_success_is_retried(mbta):
    mbta.get("/stops").mock(side_effect=[httpx.Response(502), httpx.Response(200, json=STATIONS)])

    result = payload(await call("search_stops", {"query": "harvard"}))
    assert result["stops"][0]["id"] == "place-harsq"
