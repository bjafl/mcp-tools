# mcp-tools

A monorepo of MCP (Model Context Protocol) tools, each runnable directly via `uvx --from git+...`.

## Packages

| Package | Description |
|---|---|
| [mcp-fetch-select](packages/mcp-fetch-select/) | Fetch a URL and return elements matching a CSS selector |
| [mcp-recipe-scraper](packages/mcp-recipe-scraper/) | Scrape structured recipe data (title, ingredients, instructions, nutrients) from a recipe URL |

---

## Usage with MetaMCP

Each package can be wired up individually. Example for `mcp-fetch-select`:

```json
{
  "name": "FetchSelect",
  "type": "STDIO",
  "command": "uvx",
  "args": [
    "--from",
    "git+https://github.com/YOUR_USER/mcp-tools#subdirectory=packages/mcp-fetch-select",
    "mcp-fetch-select"
  ]
}
```

### Private repo (with `GITHUB_TOKEN`)

```json
{
  "name": "FetchSelect",
  "type": "STDIO",
  "command": "uvx",
  "args": [
    "--from",
    "git+https://${GITHUB_TOKEN}@github.com/YOUR_USER/mcp-tools#subdirectory=packages/mcp-fetch-select",
    "mcp-fetch-select"
  ],
  "env": {
    "GITHUB_TOKEN": "ghp_..."
  }
}
```

---

## Local development

Run a package directly without installing:

```bash
uv --directory packages/mcp-fetch-select run mcp-fetch-select
```

Test with the MCP inspector:

```bash
npx @modelcontextprotocol/inspector uvx \
  --from "git+https://github.com/YOUR_USER/mcp-tools#subdirectory=packages/mcp-fetch-select" \
  mcp-fetch-select
```

Or point the inspector at your local copy:

```bash
npx @modelcontextprotocol/inspector \
  uv --directory packages/mcp-fetch-select run mcp-fetch-select
```

---

## Transports

Each server defaults to stdio (as used by the MetaMCP examples above). Pass `--transport
streamable-http` to serve over the modern MCP Streamable HTTP transport instead:

```bash
uv --directory packages/mcp-fetch-select run mcp-fetch-select \
  --transport streamable-http --host 127.0.0.1 --port 8000 --path /mcp
```

The server is then reachable at `http://127.0.0.1:8000/mcp`. `--host`/`--port`/`--path` are
ignored in stdio mode. `--host` defaults to `127.0.0.1`; pass `--host 0.0.0.0` to expose it
beyond localhost.

---

## Proxying outbound requests

Both servers make outbound HTTP requests (to fetch the target page). To route those through a
web proxy — e.g. a [tinyproxy](https://tinyproxy.github.io/) instance — set:

| Env var | Purpose |
|---|---|
| `MCP_PROXY_URL` | Proxy endpoint, e.g. `http://tinyproxy-host:8888` |
| `MCP_PROXY_USERNAME` | Optional Basic auth username for the proxy |
| `MCP_PROXY_PASSWORD` | Optional Basic auth password for the proxy |

```bash
MCP_PROXY_URL="http://tinyproxy-host:8888" \
MCP_PROXY_USERNAME="myuser" \
MCP_PROXY_PASSWORD="mypass" \
uv --directory packages/mcp-fetch-select run mcp-fetch-select
```

Or copy the package's `.env.example` to `.env` and run with `uv run --env-file .env
mcp-fetch-select` — `uv run` only loads a `.env` file when `--env-file` (or `UV_ENV_FILE`) is
given, it isn't picked up automatically.

When unset, requests go out directly — no proxy is used. Note that this only affects the
server's *own* env — when a client spawns the server as a stdio subprocess (as in the MetaMCP
examples above), these variables must be listed in that client's `env` config, since stdio
clients only forward a small safe-list of variables (not the whole parent environment) to the
child process by default.

---

## Adding a new package

1. Create `packages/<your-package>/` with a standalone `pyproject.toml` and `src/` layout.
2. Add an entry point under `[project.scripts]` in `pyproject.toml`.
3. Add a row to the table above in this README.

Each package is fully self-contained — no workspace-level `pyproject.toml` — so `uvx --from git+...#subdirectory=` works independently for each one.
