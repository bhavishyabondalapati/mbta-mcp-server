# MBTA MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives Claude, or any MCP client, live Boston transit data from the public [MBTA V3 API](https://api-v3.mbta.com). It provides tools to search stops, get real-time departures, and read service alerts. No API key is required.

Once connected to Claude Desktop, it answers questions such as *"When's the next Red Line train from Park Street?"* or *"Are there any Green Line delays?"*

## Features

| Tool | Description | Example arguments |
|------|-------------|-------------------|
| `search_stops` | Finds stations by name (subway, light rail, commuter rail, ferry) | `{"query": "harvard"}` |
| `next_departures` | Real-time upcoming departures, soonest first; accepts a station name or stop ID | `{"stop": "Park Street", "limit": 5, "route": "Red"}` |
| `service_alerts` | Current delays, shuttles, and closures, most severe first | `{"line": "Green"}` (all four branches), `"Orange Line"`, `"39"`, `"CR-Worcester"` |

- Errors such as unknown stations, timeouts, and rate limits are returned as readable tool errors rather than crashes.
- The station list (~276 parent stations) is cached for an hour to conserve the unauthenticated rate limit.

## Architecture

```
MCP client (Claude Desktop) ──stdio / JSON-RPC──► server.py ──► api.py ──► MBTA V3 API
                                                  (3 tools)     (async client,
                                                       │         retries, cache)
                                                       ▼
                                                  transit.py
                                                  (pure JSON parsing)
```

- **`server.py`** defines the three tools with `@mcp.tool()` on the MCP SDK v2 `MCPServer`, which builds each tool's JSON schema from type hints and docstrings. `MBTAError` is converted to the SDK's `ToolError`, so the model receives an `is_error` result it can act on.
- **`api.py`** is an async `httpx` client with a single `get()` that handles all failure modes:
  - Timeouts and 5xx responses are retried once; other 4xx responses are not retried.
  - On HTTP 429, the client reads `retry-after` / `x-ratelimit-reset`, waits and retries once if the wait is 5 s or less, and otherwise returns an error immediately.
- **`transit.py`** contains pure functions that convert the API's JSON:API responses (records in `data`, related routes and trips in `included`, linked via `relationships`) into simple dictionaries. Departures use `include=route,trip` to fetch everything in one request; predictions with no `departure_time` (trips ending at that stop) are excluded.
- The server uses stdio transport, so nothing is written to stdout except protocol messages.

| Library | Role |
|---------|------|
| [`mcp`](https://github.com/modelcontextprotocol/python-sdk) (v2) | Official MCP Python SDK |
| [`httpx`](https://www.python-httpx.org/) | Async HTTP client, so API calls do not block the server's event loop |
| [`pytest`](https://pytest.org), [`pytest-asyncio`](https://pytest-asyncio.readthedocs.io/) | Test runner with async test support |
| [`respx`](https://lundberg.github.io/respx/) | Mocks `httpx` so tests run offline and deterministically |

## Quickstart

```bash
git clone https://github.com/bhavishyabondalapati/mbta-mcp-server.git
cd mbta-mcp-server
conda create -n mbta-mcp-server python=3.12 -y
conda activate mbta-mcp-server
pip install -r requirements.txt
pip install -e .
```

This installs an `mbta-mcp-server` command. The server communicates over stdio, so run on its own it waits for input (Ctrl+C to quit):

```bash
mbta-mcp-server
```

To explore the tools in a browser with the MCP Inspector (requires Node.js):

```bash
npx @modelcontextprotocol/inspector "$(which mbta-mcp-server)"
```

### API key (optional)

Without a key, the MBTA API allows about 20 requests per minute; a free key from the [MBTA developer portal](https://api-v3.mbta.com/portal) raises this to 1000. Set `MBTA_API_KEY` in the environment or in the Claude Desktop config below.

### Claude Desktop

1. Get the absolute path to the command (Claude Desktop does not activate conda environments):
   ```bash
   conda activate mbta-mcp-server && which mbta-mcp-server
   ```
2. In Claude Desktop, open **Settings → Developer → Edit Config** (`~/Library/Application Support/Claude/claude_desktop_config.json`).
3. Add the server under `mcpServers`, using the path from step 1:
   ```json
   {
     "mcpServers": {
       "mbta": {
         "command": "/path/to/envs/mbta-mcp-server/bin/mbta-mcp-server",
         "env": { "MBTA_API_KEY": "" }
       }
     }
   }
   ```
   The `env` block is optional.
4. Quit Claude Desktop fully (Cmd+Q) and reopen it. The MBTA tools appear in the chat box's tools menu.

If the tools do not appear, check `~/Library/Logs/Claude/mcp-server-mbta.log`.

## Running tests

```bash
pytest -v
```

20 tests, all offline: `respx` intercepts every HTTP request, and any unmocked request fails the test.

- `test_transit.py`: unit tests for parsing and stop search.
- `test_tools.py`: end-to-end tests that call each tool through an in-process MCP client, including rate-limit, timeout, and server-error cases.

## Project structure

```
mbta-mcp-server/
├── mbta_mcp/
│   ├── __main__.py      Entry point for `python -m mbta_mcp`
│   ├── api.py           Async MBTA client: retries, rate-limit handling, error messages, station cache
│   ├── server.py        MCP server and its three tools
│   └── transit.py       Pure functions converting API JSON into simple dicts
├── tests/
│   ├── conftest.py      Shared fixtures and fake MBTA API responses
│   ├── test_tools.py    End-to-end tool tests through an in-process MCP client
│   └── test_transit.py  Unit tests for parsing and search helpers
├── .env.example         Placeholder for the optional MBTA_API_KEY
├── pyproject.toml       Package metadata, `mbta-mcp-server` entry point, pytest settings
└── requirements.txt     Runtime and test dependencies
```

## Design decisions

- **Tool errors over exceptions.** A `ToolError` gives the model a message it can act on, for example asking which station the user meant, instead of a generic failure.
- **Bounded retries.** One retry for transient failures, none for client errors, and no long waits on rate limits, so the model is never left waiting.
- **Separation of concerns.** Network code, data transformation, and the MCP interface are separate modules; parsing is pure and tested without the network.
- **Docstrings written for the model.** Tool descriptions come from docstrings and type hints, so they are written for an LLM reader.
- **MCP SDK v2.** The installed SDK is 2.x, where `FastMCP` was renamed to `MCPServer`.

## Limitations and future work

- Covers stops, departures, and alerts only; vehicle positions, schedules, and trip planning are not exposed.
- The station cache is in memory and refreshed hourly.
- Without an API key, heavy use can hit the ~20 requests/minute limit.
