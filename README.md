# mcp-tools

A monorepo of MCP (Model Context Protocol) tools, each runnable directly via `uvx --from git+...`.

## Requirements

- Python 3.12+ (uv will download a matching interpreter automatically if you don't have one)
- [uv](https://docs.astral.sh/uv/)

## Packages

| Package | Description |
|---|---|
| [mcp-fetch-select](packages/mcp-fetch-select/) | Fetch a URL and return elements matching a CSS selector |
| [mcp-recipe-scraper](packages/mcp-recipe-scraper/) | Scrape structured recipe data (title, ingredients, instructions, nutrients, yields) from a recipe URL |

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
    "git+https://github.com/bjafl/mcp-tools#subdirectory=packages/mcp-fetch-select",
    "mcp-fetch-select"
  ]
}
```

### Private fork (with `GITHUB_TOKEN`)

If you've forked this repo privately, authenticate with a token instead (replace `YOUR_USER`
with your fork's owner):

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
  --from "git+https://github.com/bjafl/mcp-tools#subdirectory=packages/mcp-fetch-select" \
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

| Env var | CLI flag | Purpose |
|---|---|---|
| `MCP_PROXY_URL` | `--proxy-url` | Proxy endpoint, e.g. `http://tinyproxy-host:8888` |
| `MCP_PROXY_USERNAME` | `--proxy-username` | Optional Basic auth username for the proxy |
| `MCP_PROXY_PASSWORD` | `--proxy-password` | Optional Basic auth password for the proxy |

Each CLI flag takes precedence over its env var, independently per field — e.g. you can set
`MCP_PROXY_URL`/`MCP_PROXY_USERNAME` via env and override just `--proxy-password` for a single
run.

```bash
MCP_PROXY_URL="http://tinyproxy-host:8888" \
MCP_PROXY_USERNAME="myuser" \
MCP_PROXY_PASSWORD="mypass" \
uv --directory packages/mcp-fetch-select run mcp-fetch-select
```

```bash
uv --directory packages/mcp-fetch-select run mcp-fetch-select \
  --proxy-url "http://tinyproxy-host:8888" --proxy-username myuser --proxy-password mypass
```

Or copy the package's `.env.example` to `.env` and run with:

```bash
uv --directory packages/mcp-fetch-select run --env-file .env mcp-fetch-select
```

`uv run` only loads a `.env` file when `--env-file` (or `UV_ENV_FILE`) is given — it isn't
picked up automatically.

When unset, requests go out directly — no proxy is used. Note that this only affects the
server's *own* env — when a client spawns the server as a stdio subprocess (as in the MetaMCP
examples above), these variables must be listed in that client's `env` config, since stdio
clients only forward a small safe-list of variables (not the whole parent environment) to the
child process by default.

### Falling back to a direct request

If the proxy itself doesn't respond (connection refused, DNS failure, or a timeout reaching the
proxy), set `MCP_PROXY_FALLBACK=1` or pass `--proxy-fallback` to retry the request directly
instead of failing the tool call. Either the env var or the flag enables it; there's no need to
set both.

```bash
uv --directory packages/mcp-fetch-select run mcp-fetch-select --proxy-fallback
```

A real HTTP error response from the target site relayed through a working proxy (e.g. a 404) is
not treated as a proxy failure and does not trigger the fallback. When a fallback does happen,
the tool's response text is prefixed with a note (`> Note: the proxy did not respond; this
request was sent directly (no proxy).`) so the calling agent is aware the request bypassed the
proxy.

---

## Adding a new package

1. Create `packages/<your-package>/` with a standalone `pyproject.toml` (using the `uv_build`
   backend, matching the existing packages) and `src/` layout.
2. Add an entry point under `[project.scripts]` in `pyproject.toml`.
3. Optionally register it in the root `pyproject.toml`'s `dependencies` and
   `[tool.uv.sources]` so `uv sync` at the repo root installs it into the shared workspace
   environment too. This isn't required for the package to work standalone — see below.
4. Add a row to the table above in this README.

The root `pyproject.toml` declares a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
(`[tool.uv.workspace]`) spanning `packages/*`, which is what lets `uv sync`/`uv run` at the repo
root manage both packages together. Each package's own `pyproject.toml` is still a complete,
independent project — its dependencies don't reference the workspace — so `uvx --from
git+...#subdirectory=packages/<name>` keeps working standalone, without needing the rest of the
repo or the root `pyproject.toml`.
