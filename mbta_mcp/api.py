"""A small async client for the MBTA V3 API (https://api-v3.mbta.com).

The API is public and works without a key (about 20 requests per minute).
Setting MBTA_API_KEY in the environment raises that limit, but is optional.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

BASE_URL = "https://api-v3.mbta.com"
DEFAULT_TIMEOUT = 10.0

# If the API says "wait N seconds", we only wait if N is this small.
# Anything longer is reported back to the user instead of hanging the tool.
MAX_RATE_LIMIT_WAIT = 5.0

# Stations rarely change, so we keep the list for an hour to save requests.
STATIONS_CACHE_SECONDS = 3600


class MBTAError(Exception):
    """Something went wrong talking to the MBTA API. The message is user-friendly."""


class MBTARateLimitError(MBTAError):
    """The MBTA API rejected the request because we sent too many (HTTP 429)."""


class MBTAClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_rate_limit_wait: float = MAX_RATE_LIMIT_WAIT,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("MBTA_API_KEY")
        self.base_url = base_url
        self.timeout = timeout
        self.max_rate_limit_wait = max_rate_limit_wait
        self._stations: list[dict[str, Any]] | None = None
        self._stations_fetched_at = 0.0

    async def get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """GET a JSON:API document, retrying once on rate limits or server errors."""
        headers = {"Accept": "application/vnd.api+json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, headers=headers) as http:
            for attempt in range(2):
                is_last_attempt = attempt == 1
                try:
                    response = await http.get(path, params=params)
                except httpx.TimeoutException as exc:
                    if is_last_attempt:
                        raise MBTAError("The MBTA API timed out. Please try again in a moment.") from exc
                    continue
                except httpx.HTTPError as exc:
                    raise MBTAError(f"Could not reach the MBTA API: {exc}") from exc

                if response.status_code == 429:
                    wait = _seconds_until_reset(response)
                    if is_last_attempt or wait > self.max_rate_limit_wait:
                        raise MBTARateLimitError(
                            f"The MBTA API rate limit was reached. Try again in about {round(wait)} seconds "
                            "(setting an MBTA_API_KEY raises the limit)."
                        )
                    await asyncio.sleep(wait)
                    continue

                if response.status_code >= 500:
                    if is_last_attempt:
                        raise MBTAError(f"The MBTA API is having trouble (HTTP {response.status_code}). Try again later.")
                    await asyncio.sleep(0.5)
                    continue

                if response.status_code >= 400:
                    raise MBTAError(_describe_client_error(response))

                return response.json()

        raise MBTAError("The MBTA API request failed.")  # not reached; keeps type checkers happy

    async def stations(self) -> list[dict[str, Any]]:
        """All parent stations (subway, light rail, commuter rail, ferry), cached for an hour."""
        if self._stations is None or time.monotonic() - self._stations_fetched_at > STATIONS_CACHE_SECONDS:
            doc = await self.get(
                "/stops",
                {"filter[location_type]": "1", "fields[stop]": "name,municipality,vehicle_type"},
            )
            self._stations = doc.get("data", [])
            self._stations_fetched_at = time.monotonic()
        return self._stations

    async def predictions(self, stop_id: str, route: str | None = None) -> dict[str, Any]:
        params = {
            "filter[stop]": stop_id,
            "include": "route,trip",
            "sort": "departure_time",
            "fields[route]": "long_name,short_name,type",
            "fields[trip]": "headsign",
        }
        if route:
            params["filter[route]"] = route
        return await self.get("/predictions", params)

    async def alerts(self, routes: str) -> dict[str, Any]:
        return await self.get("/alerts", {"filter[route]": routes})


def _seconds_until_reset(response: httpx.Response) -> float:
    """How long the API asks us to wait. x-ratelimit-reset is a Unix timestamp."""
    retry_after = response.headers.get("retry-after")
    if retry_after and retry_after.isdigit():
        return float(retry_after)
    reset = response.headers.get("x-ratelimit-reset")
    if reset and reset.isdigit():
        return max(0.0, float(reset) - time.time())
    return 1.0


def _describe_client_error(response: httpx.Response) -> str:
    """Turn a JSON:API error body into a short sentence."""
    detail = ""
    try:
        errors = response.json().get("errors", [])
        if errors:
            detail = errors[0].get("detail") or errors[0].get("title") or ""
    except ValueError:
        pass
    message = f"The MBTA API rejected the request (HTTP {response.status_code})"
    return f"{message}: {detail}" if detail else f"{message}."
