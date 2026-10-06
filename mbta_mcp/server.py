"""The MCP server: three tools that Claude (or any MCP client) can call."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from mbta_mcp.api import MBTAClient, MBTAError
from mbta_mcp.transit import normalize_line, parse_alerts, parse_departures, search_stations

mcp = MCPServer(
    name="mbta",
    instructions=(
        "Real-time Boston MBTA transit data. Use search_stops to find a station ID, "
        "then next_departures for upcoming trains/buses, or service_alerts for a line."
    ),
)

# One shared client so the station list cache is reused between tool calls.
client = MBTAClient()


@mcp.tool()
async def search_stops(query: str, limit: int = 10) -> dict[str, Any]:
    """Search MBTA stations by name (subway, light rail, commuter rail, ferry).

    Args:
        query: Part of the station name, e.g. "park st" or "harvard".
        limit: Maximum number of results (1-50).
    """
    limit = max(1, min(limit, 50))
    try:
        stations = await client.stations()
    except MBTAError as exc:
        raise ToolError(str(exc)) from exc

    matches = search_stations(stations, query, limit)
    return {"query": query, "count": len(matches), "stops": matches}


@mcp.tool()
async def next_departures(stop: str, limit: int = 5, route: str | None = None) -> dict[str, Any]:
    """Upcoming real-time departures from a stop, soonest first.

    Args:
        stop: A station name ("Park Street") or MBTA stop ID ("place-pktrm", or a bus stop number).
        limit: Maximum number of departures (1-20).
        route: Optional line to filter by, e.g. "Red", "Green-B", or a bus number like "39".
    """
    limit = max(1, min(limit, 20))
    try:
        stop_id, stop_name = await _resolve_stop(stop)
        doc = await client.predictions(stop_id, normalize_line(route) if route else None)
    except MBTAError as exc:
        raise ToolError(str(exc)) from exc

    departures = parse_departures(doc, limit)
    result: dict[str, Any] = {"stop_id": stop_id, "stop_name": stop_name, "departures": departures}
    if not departures:
        result["note"] = "No upcoming departures found. Service may be over for the day, or the stop ID may be wrong."
    return result


@mcp.tool()
async def service_alerts(line: str) -> dict[str, Any]:
    """Current service alerts (delays, shuttles, closures) for a line or route.

    Args:
        line: A line name like "Red", "Orange Line", "Green" (all branches), "Green-D",
            a bus route like "39", or a commuter rail ID like "CR-Worcester".
    """
    route_ids = normalize_line(line)
    try:
        doc = await client.alerts(route_ids)
    except MBTAError as exc:
        raise ToolError(str(exc)) from exc

    alerts = parse_alerts(doc)
    return {"line": line, "route_ids": route_ids.split(","), "count": len(alerts), "alerts": alerts}


async def _resolve_stop(stop: str) -> tuple[str, str | None]:
    """Turn a station name into a stop ID. Inputs that match no station are treated as IDs."""
    matches = search_stations(await client.stations(), stop, limit=5)
    if not matches:
        return stop.strip(), None
    exact = [m for m in matches if m["name"].lower() == stop.strip().lower()]
    if exact or len(matches) == 1:
        best = (exact or matches)[0]
        return best["id"], best["name"]
    options = ", ".join(f"{m['name']} ({m['id']})" for m in matches)
    raise ToolError(f"'{stop}' matches several stations: {options}. Please pass one of these stop IDs.")


def main() -> None:
    mcp.run()  # stdio transport, which is what Claude Desktop uses


if __name__ == "__main__":
    main()
