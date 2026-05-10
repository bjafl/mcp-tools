# mcp-tools

A monorepo of MCP (Model Context Protocol) tools, each runnable directly via `uvx --from git+...`.

## Packages

| Package | Description |
|---|---|
| [mcp-fetch-select](packages/mcp-fetch-select/) | Fetch a URL and return elements matching a CSS selector |

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

## Adding a new package

1. Create `packages/<your-package>/` with a standalone `pyproject.toml` and `src/` layout.
2. Add an entry point under `[project.scripts]` in `pyproject.toml`.
3. Add a row to the table above in this README.

Each package is fully self-contained — no workspace-level `pyproject.toml` — so `uvx --from git+...#subdirectory=` works independently for each one.
