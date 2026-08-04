# Proxy CLI params + direct-request fallback

**Status:** Approved
**Date:** 2026-08-04

## Summary

Two additions to the outbound-proxy support in `mcp-fetch-select` and `mcp-recipe-scraper`:

1. **CLI proxy params** — `--proxy-url`/`--proxy-username`/`--proxy-password`, each taking
   precedence over its corresponding `MCP_PROXY_*` env var on a per-field basis.
2. **Direct-request fallback** — `--proxy-fallback` / `MCP_PROXY_FALLBACK` (either enables it):
   if the configured proxy doesn't respond, retry the request directly and say so in the tool's
   own response text.

Both packages currently duplicate the entire proxy block verbatim (`_proxy_url()`, `PROXY`
module global, argparse setup in `main()`). This is intentional — each package is a fully
independent, standalone-`uvx`-installable project with no shared internal dependency (see
README's "Adding a new package" section) — so this design keeps the duplication pattern and
applies the same changes to both files identically.

## 1. CLI proxy params with per-field precedence

New argparse flags in `main()`, all `default=None`:

```
--proxy-url        (maps to MCP_PROXY_URL)
--proxy-username   (maps to MCP_PROXY_USERNAME)
--proxy-password   (maps to MCP_PROXY_PASSWORD)
```

Precedence is per-field, not all-or-nothing: each field independently resolves to its CLI value
if provided, else its env var. This lets a user set `MCP_PROXY_URL`/`MCP_PROXY_USERNAME` via env
and override only `--proxy-password` for a single run, for example.

The password is a plain CLI flag (not file/stdin-only) — consistent with `--proxy-url`/
`--proxy-username` and the trust model of a host you already control.

### Refactor of `_proxy_url()`

Split into two pure functions:

```python
def _resolve_proxy_config(
    cli_url: str | None, cli_username: str | None, cli_password: str | None
) -> str | None:
    """Merge CLI args with MCP_PROXY_* env vars, CLI taking precedence per field."""
    url = cli_url if cli_url is not None else os.environ.get("MCP_PROXY_URL")
    if not url:
        return None
    username = cli_username if cli_username is not None else os.environ.get("MCP_PROXY_USERNAME")
    password = cli_password if cli_password is not None else os.environ.get("MCP_PROXY_PASSWORD")
    return _build_proxy_url(url, username, password)


def _build_proxy_url(url: str, username: str | None, password: str | None) -> str:
    """Embed Basic auth userinfo into the proxy URL, if a username is given."""
    if not username:
        return url
    userinfo = quote(username, safe="")
    if password:
        userinfo += f":{quote(password, safe='')}"
    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, f"{userinfo}@{netloc}", parts.path, parts.query, parts.fragment))
```

`_build_proxy_url` is the existing userinfo-embedding logic, unchanged in behavior.

### Structural change: move `PROXY` assignment into `main()`

Today `PROXY = _proxy_url()` runs once at *import time*, before argparse parses anything. Since
proxy config now depends on CLI args, this must move into `main()`, after
`parser.parse_args()`:

```python
def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-fetch-select")
    # ... existing --transport/--host/--port/--path ...
    parser.add_argument("--proxy-url", default=None, help="Proxy endpoint (overrides MCP_PROXY_URL)")
    parser.add_argument("--proxy-username", default=None, help="Proxy Basic auth username (overrides MCP_PROXY_USERNAME)")
    parser.add_argument("--proxy-password", default=None, help="Proxy Basic auth password (overrides MCP_PROXY_PASSWORD)")
    parser.add_argument("--proxy-fallback", action="store_true", help="Fall back to a direct request if the proxy doesn't respond (or set MCP_PROXY_FALLBACK)")
    args = parser.parse_args()

    global PROXY, PROXY_FALLBACK
    PROXY = _resolve_proxy_config(args.proxy_url, args.proxy_username, args.proxy_password)
    PROXY_FALLBACK = args.proxy_fallback or _env_flag("MCP_PROXY_FALLBACK")

    # ... existing app.run() dispatch ...
```

`PROXY` and `PROXY_FALLBACK` stay as module-level globals (default `None`/`False` at import
time), read by the tool functions at call time. This is safe: Python resolves a bare name
inside a function body when the function is *called*, not when it's defined, and `app.run()`
doesn't dispatch any tool call until well after `main()` has finished parsing args and setting
the globals.

## 2. Direct-request fallback on proxy failure

`PROXY_FALLBACK` is a boolean resolved from `args.proxy_fallback OR _env_flag("MCP_PROXY_FALLBACK")`
(env truthy values: `1`, `true`, `yes`, `on`, case-insensitive). No precedence conflict to
resolve since it's a pure on-switch — either source enables it.

```python
def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")
```

When `PROXY_FALLBACK` is `True` and a proxy is configured, outbound requests go through a shared
helper:

```python
PROXY_FALLBACK_TIMEOUT = 10.0  # short leg: fail fast on a dead/stalled proxy

async def _fetch(url: str) -> tuple[httpx.Response, bool]:
    """GET url. Returns (response, used_fallback)."""
    if PROXY and PROXY_FALLBACK:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=PROXY_FALLBACK_TIMEOUT, proxy=PROXY
            ) as client:
                response = await client.get(url, headers=HEADERS)
                response.raise_for_status()
                return response, False
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ProxyError):
            print(f"proxy did not respond, falling back to a direct request for {url}", file=sys.stderr)
            async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT) as client:
                response = await client.get(url, headers=HEADERS)
                response.raise_for_status()
                return response, True

    async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT, proxy=PROXY) as client:
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()
        return response, False
```

Trigger condition is deliberately narrow: only `httpx.ConnectError`, `httpx.TimeoutException`,
and `httpx.ProxyError` — network-level failures reaching the proxy itself — trigger a direct
retry. `httpx.HTTPStatusError` (raised by `raise_for_status()` when the proxy *did* respond and
relayed a real answer from the target site, e.g. a 404) is not caught here and propagates
normally; a proxy successfully relaying an error response is not a proxy failure.

The short `PROXY_FALLBACK_TIMEOUT` (10s) bounds worst-case latency to ~30s (10s failed proxy
attempt + 20s direct attempt) instead of doubling the full 20s timeout on both legs. This timeout
is only used on the proxied leg when fallback is enabled; the direct retry and the
fallback-disabled path both keep the existing `TIMEOUT = 20.0`.

When `--proxy-fallback`/`MCP_PROXY_FALLBACK` is unset (the default) or no proxy is configured,
behavior is unchanged from today: one request, `TIMEOUT=20.0`, `proxy=PROXY`.

### Surfacing fallback to the calling agent

Both tool functions call `_fetch()` and check the returned `used_fallback` flag. If `True`, they
prepend a note to the text they return — visible to the calling agent in the tool's own response,
not just a server-side stderr log:

```python
response, used_fallback = await _fetch(url)
# ... build the normal `parts` / `lines` list ...
if used_fallback:
    parts.insert(0, "> Note: the proxy did not respond; this request was sent directly (no proxy).")
return "\n\n---\n\n".join(parts)
```

`fetch_select` inserts into its `parts` list before the match content; `scrape_recipe` inserts
into its `lines` list before the recipe markdown. Same note text in both.

## 3. Documentation updates

- `README.md`, "Proxying outbound requests" section: document the three new CLI flags, the
  per-field CLI-over-env precedence rule, and `--proxy-fallback`/`MCP_PROXY_FALLBACK`.
- Both packages' `.env.example`: add a commented-out `#MCP_PROXY_FALLBACK=1` line, matching the
  existing style.

## 4. Testing

No test suite exists yet for either package. Add `test_proxy.py` per package (duplicated, same
rationale as the production code) covering:

- `_resolve_proxy_config`: CLI value wins when set; env value wins when CLI arg is `None`;
  fields resolve independently (e.g. CLI username + env URL); returns `None` when no URL
  resolves from either source.
- `_build_proxy_url`: unchanged existing behavior (userinfo embedding, with/without password).
- `_fetch` fallback trigger: mock the proxied `client.get` to raise `ConnectError` /
  `TimeoutException` / `ProxyError` → assert a direct retry happens and `used_fallback` is
  `True`. Mock it to raise `HTTPStatusError` → assert no retry, exception propagates,
  `used_fallback` never observed as `True`.
- Tool-level: with `used_fallback=True`, assert the returned text starts with the fallback note.
