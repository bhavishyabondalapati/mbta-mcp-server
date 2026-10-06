"""Pure helper functions that turn raw MBTA JSON:API data into simple dicts.

Nothing here makes network calls, which keeps it easy to test.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

ROUTE_TYPES = {0: "Light Rail", 1: "Subway", 2: "Commuter Rail", 3: "Bus", 4: "Ferry"}

# Friendly line names -> MBTA route IDs. Anything not listed is passed through as-is,
# so bus numbers ("1", "SL1") and commuter rail IDs ("CR-Worcester") still work.
LINE_ALIASES = {
    "red": "Red",
    "orange": "Orange",
    "blue": "Blue",
    "mattapan": "Mattapan",
    "green": "Green-B,Green-C,Green-D,Green-E",
    "green-b": "Green-B",
    "green-c": "Green-C",
    "green-d": "Green-D",
    "green-e": "Green-E",
}


def normalize_line(line: str) -> str:
    """'Red Line' -> 'Red', 'green' -> all four Green branches, '39' -> '39'."""
    key = line.strip().lower()
    for suffix in (" line", " branch"):
        key = key.removesuffix(suffix)
    key = key.replace(" ", "-")
    return LINE_ALIASES.get(key, line.strip())


def search_stations(stations: list[dict[str, Any]], query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Case-insensitive name search. Exact matches first, then prefix, then contains."""
    words = query.lower().split()
    if not words:
        return []
    phrase = " ".join(words)

    ranked = []
    for stop in stations:
        name = stop["attributes"]["name"]
        lowered = name.lower()
        if not all(word in lowered for word in words):
            continue
        rank = 0 if lowered == phrase else 1 if lowered.startswith(phrase) else 2
        ranked.append((rank, name, stop))

    ranked.sort(key=lambda item: (item[0], item[1]))
    return [
        {
            "id": stop["id"],
            "name": stop["attributes"]["name"],
            "municipality": stop["attributes"].get("municipality"),
        }
        for _, _, stop in ranked[:limit]
    ]


def parse_departures(doc: dict[str, Any], limit: int, now: datetime | None = None) -> list[dict[str, Any]]:
    """Upcoming departures from a /predictions response, soonest first.

    Predictions with no departure_time are trains ending their trip at this stop,
    so they are skipped. Departures already in the past are skipped too.
    """
    now = now or datetime.now(timezone.utc)
    included = {(item["type"], item["id"]): item["attributes"] for item in doc.get("included", [])}

    departures = []
    for prediction in doc.get("data", []):
        attrs = prediction["attributes"]
        if not attrs.get("departure_time"):
            continue
        departs_at = datetime.fromisoformat(attrs["departure_time"])
        if departs_at < now:
            continue

        route_id = _related_id(prediction, "route")
        trip_id = _related_id(prediction, "trip")
        route = included.get(("route", route_id), {})
        trip = included.get(("trip", trip_id), {})

        departures.append(
            {
                "route": route.get("long_name") or route.get("short_name") or route_id,
                "route_id": route_id,
                "mode": ROUTE_TYPES.get(route.get("type"), "Unknown"),
                "headsign": trip.get("headsign") or attrs.get("trip_headsign") or "Unknown",
                "departure_time": attrs["departure_time"],
                "minutes_away": int((departs_at - now).total_seconds() // 60),
                "status": attrs.get("status"),
            }
        )

    departures.sort(key=lambda d: d["departure_time"])
    return departures[:limit]


def parse_alerts(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Service alerts, most severe first."""
    alerts = []
    for alert in doc.get("data", []):
        attrs = alert["attributes"]
        alerts.append(
            {
                "id": alert["id"],
                "effect": attrs.get("effect"),
                "severity": attrs.get("severity"),
                "summary": attrs.get("service_effect") or attrs.get("short_header") or attrs.get("header"),
                "header": attrs.get("header"),
                "lifecycle": attrs.get("lifecycle"),
                "timeframe": attrs.get("timeframe"),
                "url": attrs.get("url"),
            }
        )
    alerts.sort(key=lambda a: a["severity"] or 0, reverse=True)
    return alerts


def _related_id(resource: dict[str, Any], name: str) -> str | None:
    data = resource.get("relationships", {}).get(name, {}).get("data")
    return data["id"] if data else None
