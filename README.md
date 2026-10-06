# MBTA MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives Claude (or any MCP client) live Boston transit data from the public [MBTA V3 API](https://api-v3.mbta.com). It has three tools: **search stops by name**, **next departures from a stop**, and **service alerts for a line**. No API key is needed.

Once it's connected to Claude Desktop you can ask things like *"When's the next Red Line train from Park Street?"* or *"Are there any Green Line delays?"*

## Tools

| Tool | What it does | Example arguments |
|------|-------------|-------------------|
| `search_stops` | Finds stations by name (subway, light rail, commuter rail, ferry) | `{"query": "harvard"}` |
| `next_departures` | Real-time upcoming departures, soonest first. Accepts a station name or a stop ID | `{"stop": "Park Street", "limit": 5, "route": "Red"}` |
| `service_alerts` | Current delays, shuttles, and closures, most severe first | `{"line": "Green"}` (all four branches), `"Orange Line"`, `"39"`, `"CR-Worcester"` |

## Tools and libraries used

| Library | Why |
|---------|-----|
| [`mcp`](https://github.com/modelcontextprotocol/python-sdk) (v2) | The official MCP Python SDK. Its `MCPServer` class turns plain Python functions into MCP tools, building the JSON schema from type hints and docstrings. |
| [`httpx`](https://www.python-httpx.org/) | An HTTP client with `async` support. MCP tools run in an async event loop, so a blocking library like `requests` would stall the server. |
| [`pytest`](https://pytest.org) + [`pytest-asyncio`](https://pytest-asyncio.readthedocs.io/) | Runs the tests. `pytest-asyncio` allows `async def` test functions. |
| [`respx`](https://lundberg.github.io/respx/) | Mocks `httpx` requests, so the tests never touch the real API. They run offline, fast, and give the same result every time. |

## File structure

```
mbta-mcp-server/
├── mbta_mcp/
│   ├── __init__.py      # Marks the folder as a Python package
│   ├── __main__.py      # Lets you run the server with `python -m mbta_mcp`
│   ├── api.py           # Async MBTA API client: retries, rate-limit handling, error messages, station cache
│   ├── server.py        # The MCP server and its three tools
│   └── transit.py       # Pure functions that turn raw API JSON into simple dicts (no network)
├── tests/
│   ├── __init__.py      # Makes `tests` importable so the test files can share fixtures
│   ├── conftest.py      # Shared fixtures and fake MBTA API responses
│   ├── test_tools.py    # End-to-end tests that call each tool through a real in-process MCP client
│   └── test_transit.py  # Unit tests for the parsing and search helpers
├── .env.example         # Placeholder for the optional MBTA_API_KEY
├── .gitignore           # Keeps secrets, caches, and build files out of git
├── pyproject.toml       # Package metadata, the `mbta-mcp-server` command, and pytest settings
├── requirements.txt     # Runtime and test dependencies
└── README.md            # This file
```

## Setup

```bash
git clone https://github.com/bhavishyabondalapati/mbta-mcp-server.git
cd mbta-mcp-server
conda create -n mbta-mcp-server python=3.12 -y
conda activate mbta-mcp-server
pip install -r requirements.txt
pip install -e .
```

`pip install -e .` installs the project in "editable" mode. It creates a `mbta-mcp-server` command that runs the code in this folder, so your edits take effect without reinstalling.

**Optional API key.** The API allows about 20 requests per minute without a key. A free key from the [MBTA developer portal](https://api-v3.mbta.com/portal) raises that to 1000 per minute. To use one, set `MBTA_API_KEY` in your shell or in the Claude Desktop config shown below. Never commit a real key.

## How to run it

The server speaks MCP over **stdio**: an MCP client starts it as a subprocess and talks to it through stdin and stdout. Run on its own, it just waits for input (Ctrl+C to quit):

```bash
mbta-mcp-server
```

To click through the tools in a browser, use the MCP Inspector (needs Node.js):

```bash
npx @modelcontextprotocol/inspector /opt/anaconda3/envs/mbta-mcp-server/bin/mbta-mcp-server
```

### Connect it to Claude Desktop

1. Find the full path to the command. Claude Desktop does not load your conda environment, so it needs the absolute path:
   ```bash
   conda activate mbta-mcp-server && which mbta-mcp-server
   ```
   On this machine that's `/opt/anaconda3/envs/mbta-mcp-server/bin/mbta-mcp-server`.
2. In Claude Desktop, open **Settings → Developer → Edit Config**. This opens `~/Library/Application Support/Claude/claude_desktop_config.json`.
3. Add the server under `mcpServers`, using your path from step 1:
   ```json
   {
     "mcpServers": {
       "mbta": {
         "command": "/opt/anaconda3/envs/mbta-mcp-server/bin/mbta-mcp-server",
         "env": { "MBTA_API_KEY": "" }
       }
     }
   }
   ```
   The `env` block is optional. Leave the key empty unless you have one.
4. Fully quit Claude Desktop (Cmd+Q) and reopen it. The MBTA tools should appear under the tools/connectors menu in the chat box.
5. Ask: *"What are the next departures from Harvard?"*

If the tools don't show up, check the logs at `~/Library/Logs/Claude/mcp-server-mbta.log`.

### Run the tests

```bash
pytest -v
```

None of the tests need internet access. `respx` intercepts every HTTP request, and any request that isn't mocked makes the test fail.

## How it was built

1. Created a conda environment and installed the MCP SDK. The installed version was 2.x, where `FastMCP` had been renamed to `MCPServer`, so the code uses the v2 API.
2. Called the real MBTA API with `curl` to learn the response shapes. Found that predictions with no `departure_time` are trains ending their trip at that stop, that there are only ~276 parent stations (small enough to cache), and that the rate limit shows up in `x-ratelimit-*` headers.
3. Wrote `api.py`: one `get()` method handles every error case (timeouts, 429s, 5xx, 4xx) in one place and raises a friendly `MBTAError`.
4. Wrote `transit.py` with pure parsing functions, kept separate from the network code so they're easy to test.
5. Wrote `server.py`: three `@mcp.tool()` functions that convert `MBTAError` into the SDK's `ToolError`, so Claude gets a readable error instead of a crash.
6. Wrote tests with mocked responses, including rate-limit, timeout, and server-error cases, and an in-process MCP client to test the full tool path.
7. Smoke-tested once over real stdio against the live API, then wrote this README.

## Key concepts

- **MCP (Model Context Protocol).** An open standard for connecting LLM apps to tools and data. The server advertises tools (a name, a description, and a JSON schema for the inputs), and the client (Claude Desktop) lets the model decide when to call them. Docstrings and type hints become the tool descriptions, which is why they're written for the model to read.
- **stdio transport.** For local servers, the client starts the server as a child process and exchanges JSON-RPC messages over stdin and stdout. That's why the server must never `print()` to stdout: it would corrupt the protocol stream.
- **Tool errors vs. crashes.** Raising `ToolError` returns a result marked `is_error: true` with a message the model can read and act on, for example by asking the user which "station" they meant. An unhandled exception would only produce a generic failure.
- **Rate limiting (HTTP 429).** The API limits how often you can call it. The client reads `retry-after` / `x-ratelimit-reset` to find out how long to wait. If the wait is short (≤ 5 s) it waits and retries once. Otherwise it returns an error right away, so the model isn't left hanging.
- **Retries with limits.** Timeouts and 5xx errors are often temporary, so they get one retry. 4xx errors mean the request itself was wrong, so retrying won't help.
- **Caching.** The station list barely changes, so it's fetched once an hour instead of on every search. This saves requests under the 20/minute limit.
- **async/await.** Network calls spend most of their time waiting. `async` lets the server do other work while it waits instead of blocking.
- **JSON:API.** The MBTA uses the JSON:API format: the main records go in `data`, related records (routes, trips) go in `included`, and the two are linked through `relationships`. `include=route,trip` fetches everything in one request.
- **Mocking in tests.** `respx` swaps the real network for canned responses. That makes tests deterministic, lets you simulate hard-to-trigger failures like a 429, and lets the tests run on CI without internet.
- **Separation of concerns.** Network code (`api.py`), data transformation (`transit.py`), and the MCP interface (`server.py`) live in separate files, so each can be understood and tested on its own.
