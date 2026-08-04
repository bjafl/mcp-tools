# Proxy CLI Params + Direct-Request Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `mcp-fetch-select` and `mcp-recipe-scraper` accept proxy config via CLI flags (taking precedence over the existing `MCP_PROXY_*` env vars, per field), and optionally fall back to a direct request — with a note in the tool's own response — when the configured proxy doesn't respond.

**Architecture:** Both packages currently duplicate an identical proxy block in their `__main__.py` (`_proxy_url()`, module-level `PROXY`, argparse setup). This plan keeps that duplication (each package must stay independently `uvx`-installable with no shared internal dependency) and applies the same changes to both files: split `_proxy_url()` into `_resolve_proxy_config()` (CLI/env merge) + `_build_proxy_url()` (userinfo embedding, unchanged logic), move the `PROXY` global's assignment from import-time into `main()` (since it now depends on parsed CLI args), and add a `_fetch()` helper that tries the proxy with a short timeout, falls back to a direct request on network-level failure, and reports whether it did so.

**Tech Stack:** Python 3.12+, `httpx` (existing dependency, no version change), `pytest>=8,<9` (new dev dependency, one per package). No new runtime dependencies.

## Global Constraints

- Python 3.12+, matching each package's existing `requires-python = ">=3.12"`.
- Dependency version pins follow the existing `>=X,<Y` style used in each package's `pyproject.toml`.
- No shared internal package between `mcp-fetch-select` and `mcp-recipe-scraper` — duplicate the proxy code identically in both, per the README's "each package is a fully independent, standalone project" design goal.
- Existing `TIMEOUT = 20.0` is unchanged and still used for the non-fallback path and the direct-retry leg. New `PROXY_FALLBACK_TIMEOUT = 10.0` applies only to the proxied leg when `--proxy-fallback`/`MCP_PROXY_FALLBACK` is enabled.
- Fallback trigger is narrow: only `httpx.ConnectError`, `httpx.TimeoutException`, `httpx.ProxyError` (network-level failures reaching the proxy). `httpx.HTTPStatusError` (a real response from the target site, relayed through a working proxy) must propagate normally — never triggers fallback.
- New CLI flags: `--proxy-url`, `--proxy-username`, `--proxy-password` (all `default=None`, each independently overriding its `MCP_PROXY_URL`/`MCP_PROXY_USERNAME`/`MCP_PROXY_PASSWORD` env var when set), and `--proxy-fallback` (`action="store_true"`, env equivalent `MCP_PROXY_FALLBACK` with truthy values `1`/`true`/`yes`/`on` case-insensitive; either source enables it).
- Fallback note text, identical in both packages: `"> Note: the proxy did not respond; this request was sent directly (no proxy)."` (module constant `NOTE_PROXY_FALLBACK`).
- Spec: `docs/superpowers/specs/2026-08-04-proxy-cli-and-fallback-design.md`.

## File Structure

- `packages/mcp-fetch-select/src/mcp_fetch_select/__main__.py` — modify: proxy config resolution, CLI flags, `_fetch()`, `fetch_select()` wiring.
- `packages/mcp-fetch-select/pyproject.toml` — modify: add `pytest` dev dependency group.
- `packages/mcp-fetch-select/tests/test_proxy.py` — create: unit tests for proxy config resolution and fallback.
- `packages/mcp-fetch-select/.env.example` — modify: document `MCP_PROXY_FALLBACK`.
- `packages/mcp-recipe-scraper/src/mcp_recipe_scraper/__main__.py` — modify: same shape as fetch-select's, adapted for `scrape_recipe()`.
- `packages/mcp-recipe-scraper/pyproject.toml` — modify: add `pytest` dev dependency group.
- `packages/mcp-recipe-scraper/tests/test_proxy.py` — create: same test shape as fetch-select's.
- `packages/mcp-recipe-scraper/.env.example` — modify: document `MCP_PROXY_FALLBACK`.
- `README.md` — modify: "Proxying outbound requests" section — new flags, precedence rule, fallback subsection.

---

### Task 1: mcp-fetch-select — proxy config resolution with CLI precedence

**Files:**
- Modify: `packages/mcp-fetch-select/src/mcp_fetch_select/__main__.py`
- Modify: `packages/mcp-fetch-select/pyproject.toml`
- Create: `packages/mcp-fetch-select/tests/test_proxy.py`

**Interfaces:**
- Produces: `_resolve_proxy_config(cli_url: str | None, cli_username: str | None, cli_password: str | None) -> str | None` — merges CLI args with `MCP_PROXY_URL`/`MCP_PROXY_USERNAME`/`MCP_PROXY_PASSWORD` env vars, CLI value wins per field when not `None`.
- Produces: `_build_proxy_url(url: str, username: str | None, password: str | None) -> str` — embeds Basic auth userinfo into `url` if `username` is truthy (unchanged logic, extracted from the old `_proxy_url()`).
- Produces: module-level `PROXY: str | None` — set inside `main()` after parsing args (no longer set at import time). Later tasks (Task 2) read this global from `_fetch()`.

- [ ] **Step 1: Add pytest as a dev dependency**

Add to the end of `packages/mcp-fetch-select/pyproject.toml`:

```toml

[dependency-groups]
dev = ["pytest>=8,<9"]
```

- [ ] **Step 2: Write the failing tests**

Create `packages/mcp-fetch-select/tests/test_proxy.py`:

```python
from mcp_fetch_select.__main__ import _build_proxy_url, _resolve_proxy_config


def test_resolve_proxy_config_cli_wins_over_env(monkeypatch):
    monkeypatch.setenv("MCP_PROXY_URL", "http://env-proxy:8888")
    monkeypatch.setenv("MCP_PROXY_USERNAME", "env-user")
    monkeypatch.setenv("MCP_PROXY_PASSWORD", "env-pass")

    result = _resolve_proxy_config("http://cli-proxy:9999", "cli-user", "cli-pass")

    assert result == "http://cli-user:cli-pass@cli-proxy:9999"


def test_resolve_proxy_config_env_wins_when_cli_is_none(monkeypatch):
    monkeypatch.setenv("MCP_PROXY_URL", "http://env-proxy:8888")
    monkeypatch.setenv("MCP_PROXY_USERNAME", "env-user")
    monkeypatch.setenv("MCP_PROXY_PASSWORD", "env-pass")

    result = _resolve_proxy_config(None, None, None)

    assert result == "http://env-user:env-pass@env-proxy:8888"


def test_resolve_proxy_config_fields_resolve_independently(monkeypatch):
    monkeypatch.setenv("MCP_PROXY_URL", "http://env-proxy:8888")
    monkeypatch.delenv("MCP_PROXY_USERNAME", raising=False)
    monkeypatch.delenv("MCP_PROXY_PASSWORD", raising=False)

    result = _resolve_proxy_config(None, "cli-user", None)

    assert result == "http://cli-user@env-proxy:8888"


def test_resolve_proxy_config_returns_none_without_url(monkeypatch):
    monkeypatch.delenv("MCP_PROXY_URL", raising=False)

    result = _resolve_proxy_config(None, None, None)

    assert result is None


def test_build_proxy_url_without_username():
    assert _build_proxy_url("http://proxy:8888", None, None) == "http://proxy:8888"


def test_build_proxy_url_with_username_and_password():
    result = _build_proxy_url("http://proxy:8888", "user", "pass")

    assert result == "http://user:pass@proxy:8888"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv --directory packages/mcp-fetch-select run pytest tests/test_proxy.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name '_build_proxy_url'` (neither function exists yet).

- [ ] **Step 4: Replace `_proxy_url()` with `_resolve_proxy_config()` + `_build_proxy_url()`, and add the CLI flags**

In `packages/mcp-fetch-select/src/mcp_fetch_select/__main__.py`, replace the existing block (the `_proxy_url()` function definition through the `PROXY = _proxy_url()` line, currently lines 29-54) with:

```python
PROXY: str | None = None


def _resolve_proxy_config(
    cli_url: str | None, cli_username: str | None, cli_password: str | None
) -> str | None:
    """Merge CLI proxy args with MCP_PROXY_* env vars, CLI winning per field."""
    url = cli_url if cli_url is not None else os.environ.get("MCP_PROXY_URL")
    if not url:
        return None
    username = cli_username if cli_username is not None else os.environ.get("MCP_PROXY_USERNAME")
    password = cli_password if cli_password is not None else os.environ.get("MCP_PROXY_PASSWORD")
    return _build_proxy_url(url, username, password)


def _build_proxy_url(url: str, username: str | None, password: str | None) -> str:
    """Embed Basic auth userinfo into a proxy URL, if a username is given."""
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

Then update `main()` to add the three new flags and resolve `PROXY` after parsing, replacing the existing `main()` body:

```python
def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-fetch-select")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to serve over (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (streamable-http only)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (streamable-http only)")
    parser.add_argument("--path", default="/mcp", help="HTTP path for the MCP endpoint (streamable-http only)")
    parser.add_argument(
        "--proxy-url",
        default=None,
        help="Proxy endpoint for outbound requests, e.g. http://tinyproxy-host:8888 (overrides MCP_PROXY_URL)",
    )
    parser.add_argument(
        "--proxy-username",
        default=None,
        help="Basic auth username for the proxy (overrides MCP_PROXY_USERNAME)",
    )
    parser.add_argument(
        "--proxy-password",
        default=None,
        help="Basic auth password for the proxy (overrides MCP_PROXY_PASSWORD)",
    )
    args = parser.parse_args()

    global PROXY
    PROXY = _resolve_proxy_config(args.proxy_url, args.proxy_username, args.proxy_password)

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()
```

`fetch_select()` itself is untouched in this task — it still reads the module-level `PROXY` global exactly as before.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv --directory packages/mcp-fetch-select run pytest tests/test_proxy.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add packages/mcp-fetch-select/pyproject.toml packages/mcp-fetch-select/src/mcp_fetch_select/__main__.py packages/mcp-fetch-select/tests/test_proxy.py
git commit -m "feat(mcp-fetch-select): add CLI proxy params with per-field precedence over env"
```

---

### Task 2: mcp-fetch-select — direct-request fallback

**Files:**
- Modify: `packages/mcp-fetch-select/src/mcp_fetch_select/__main__.py`
- Modify: `packages/mcp-fetch-select/tests/test_proxy.py`

**Interfaces:**
- Consumes: `PROXY: str | None`, `_resolve_proxy_config` (Task 1).
- Produces: `_env_flag(name: str) -> bool`.
- Produces: `_fetch(url: str) -> tuple[httpx.Response, bool]` — second element is `used_fallback`.
- Produces: module-level `PROXY_FALLBACK: bool` and `PROXY_FALLBACK_TIMEOUT = 10.0`.
- Produces: module-level `NOTE_PROXY_FALLBACK: str` constant, reused by Task 4's `scrape_recipe()`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/mcp-fetch-select/tests/test_proxy.py` (add these imports at the top, alongside the existing ones):

```python
import asyncio

import httpx
import pytest

import mcp_fetch_select.__main__ as main_mod
from mcp_fetch_select.__main__ import _env_flag, _fetch, fetch_select
```

Append these test functions to the file:

```python
def test_env_flag_true_values(monkeypatch):
    for value in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv("MCP_PROXY_FALLBACK", value)
        assert _env_flag("MCP_PROXY_FALLBACK") is True


def test_env_flag_false_when_unset(monkeypatch):
    monkeypatch.delenv("MCP_PROXY_FALLBACK", raising=False)
    assert _env_flag("MCP_PROXY_FALLBACK") is False


class _FakeAsyncClient:
    """Records the proxy it was constructed with and delegates .get() to a callback."""

    def __init__(self, get_impl, follow_redirects=True, timeout=None, proxy=None):
        self.proxy = proxy
        self._get_impl = get_impl

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, headers=None):
        return await self._get_impl(self.proxy, url)


def test_fetch_uses_proxy_when_fallback_disabled(monkeypatch):
    monkeypatch.setattr(main_mod, "PROXY", "http://proxy:8888")
    monkeypatch.setattr(main_mod, "PROXY_FALLBACK", False)
    seen_proxies = []

    async def get_impl(proxy, url):
        seen_proxies.append(proxy)
        return httpx.Response(200, request=httpx.Request("GET", url), text="ok")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(get_impl, **kw))

    response, used_fallback = asyncio.run(_fetch("http://example.com"))

    assert used_fallback is False
    assert response.text == "ok"
    assert seen_proxies == ["http://proxy:8888"]


def test_fetch_falls_back_on_connect_error(monkeypatch):
    monkeypatch.setattr(main_mod, "PROXY", "http://proxy:8888")
    monkeypatch.setattr(main_mod, "PROXY_FALLBACK", True)
    seen_proxies = []

    async def get_impl(proxy, url):
        seen_proxies.append(proxy)
        if proxy:
            raise httpx.ConnectError("boom", request=httpx.Request("GET", url))
        return httpx.Response(200, request=httpx.Request("GET", url), text="direct ok")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(get_impl, **kw))

    response, used_fallback = asyncio.run(_fetch("http://example.com"))

    assert used_fallback is True
    assert response.text == "direct ok"
    assert seen_proxies == ["http://proxy:8888", None]


def test_fetch_does_not_fall_back_on_http_status_error(monkeypatch):
    monkeypatch.setattr(main_mod, "PROXY", "http://proxy:8888")
    monkeypatch.setattr(main_mod, "PROXY_FALLBACK", True)
    call_count = 0

    async def get_impl(proxy, url):
        nonlocal call_count
        call_count += 1
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(get_impl, **kw))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_fetch("http://example.com"))

    assert call_count == 1


def test_fetch_select_prepends_note_when_fallback_used(monkeypatch):
    async def fake_fetch(url):
        return httpx.Response(200, request=httpx.Request("GET", url), text="<p class='x'>hi</p>"), True

    monkeypatch.setattr(main_mod, "_fetch", fake_fetch)

    result = asyncio.run(fetch_select(url="http://example.com", selector=".x"))

    assert result.startswith("> Note: the proxy did not respond")
    assert "hi" in result


def test_fetch_select_no_note_without_fallback(monkeypatch):
    async def fake_fetch(url):
        return httpx.Response(200, request=httpx.Request("GET", url), text="<p class='x'>hi</p>"), False

    monkeypatch.setattr(main_mod, "_fetch", fake_fetch)

    result = asyncio.run(fetch_select(url="http://example.com", selector=".x"))

    assert not result.startswith("> Note:")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv --directory packages/mcp-fetch-select run pytest tests/test_proxy.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name '_env_flag'` (nothing from this task exists yet).

- [ ] **Step 3: Add `sys` import, the fallback globals, `_env_flag`, `_fetch`, and the `--proxy-fallback` flag**

In `packages/mcp-fetch-select/src/mcp_fetch_select/__main__.py`, add `import sys` to the top import block (alongside the existing `import argparse` / `import os`).

Replace the `PROXY: str | None = None` line (added in Task 1) with:

```python
PROXY: str | None = None
PROXY_FALLBACK = False
PROXY_FALLBACK_TIMEOUT = 10.0
NOTE_PROXY_FALLBACK = "> Note: the proxy did not respond; this request was sent directly (no proxy)."
```

Add `_env_flag` and `_fetch` right after `_build_proxy_url`'s definition:

```python
def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def _fetch(url: str) -> tuple[httpx.Response, bool]:
    """GET url, honoring PROXY/PROXY_FALLBACK. Returns (response, used_fallback)."""
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

Add the `--proxy-fallback` flag in `main()`, right after the `--proxy-password` argument:

```python
    parser.add_argument(
        "--proxy-fallback",
        action="store_true",
        help="Fall back to a direct request if the proxy doesn't respond (or set MCP_PROXY_FALLBACK)",
    )
```

And update the `global`/resolution lines in `main()`:

```python
    global PROXY, PROXY_FALLBACK
    PROXY = _resolve_proxy_config(args.proxy_url, args.proxy_username, args.proxy_password)
    PROXY_FALLBACK = args.proxy_fallback or _env_flag("MCP_PROXY_FALLBACK")
```

- [ ] **Step 4: Wire `fetch_select()` to use `_fetch()` and prepend the note**

Replace the body of `fetch_select()` (currently the `async with httpx.AsyncClient(...)` block through the `soup = BeautifulSoup(...)` line) with:

```python
    response, used_fallback = await _fetch(url)
    prefix = f"{NOTE_PROXY_FALLBACK}\n\n" if used_fallback else ""

    soup = BeautifulSoup(response.text, "lxml")
```

And update the two `return` statements later in the same function:

```python
    if not matches:
        return f"{prefix}No matches found for selector '{selector}' on {url}"

    parts = [f"# {len(matches)} match(es) for '{selector}' on {url}"]
    for el in matches:
        if raw_html:
            parts.append(str(el))
        else:
            parts.append(el.get_text(separator="\n", strip=True))

    return prefix + "\n\n---\n\n".join(parts)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv --directory packages/mcp-fetch-select run pytest tests/test_proxy.py -v`
Expected: PASS (13 tests: 6 from Task 1 + 7 new)

- [ ] **Step 6: Commit**

```bash
git add packages/mcp-fetch-select/src/mcp_fetch_select/__main__.py packages/mcp-fetch-select/tests/test_proxy.py
git commit -m "feat(mcp-fetch-select): fall back to a direct request when the proxy doesn't respond"
```

---

### Task 3: mcp-recipe-scraper — proxy config resolution with CLI precedence

**Files:**
- Modify: `packages/mcp-recipe-scraper/src/mcp_recipe_scraper/__main__.py`
- Modify: `packages/mcp-recipe-scraper/pyproject.toml`
- Create: `packages/mcp-recipe-scraper/tests/test_proxy.py`

**Interfaces:**
- Produces: `_resolve_proxy_config(cli_url: str | None, cli_username: str | None, cli_password: str | None) -> str | None` — identical contract to Task 1's, duplicated in this package.
- Produces: `_build_proxy_url(url: str, username: str | None, password: str | None) -> str` — identical contract to Task 1's.
- Produces: module-level `PROXY: str | None`, set inside `main()`.

This mirrors Task 1 exactly, applied to `mcp-recipe-scraper`.

- [ ] **Step 1: Add pytest as a dev dependency**

Add to the end of `packages/mcp-recipe-scraper/pyproject.toml`:

```toml

[dependency-groups]
dev = ["pytest>=8,<9"]
```

- [ ] **Step 2: Write the failing tests**

Create `packages/mcp-recipe-scraper/tests/test_proxy.py`:

```python
from mcp_recipe_scraper.__main__ import _build_proxy_url, _resolve_proxy_config


def test_resolve_proxy_config_cli_wins_over_env(monkeypatch):
    monkeypatch.setenv("MCP_PROXY_URL", "http://env-proxy:8888")
    monkeypatch.setenv("MCP_PROXY_USERNAME", "env-user")
    monkeypatch.setenv("MCP_PROXY_PASSWORD", "env-pass")

    result = _resolve_proxy_config("http://cli-proxy:9999", "cli-user", "cli-pass")

    assert result == "http://cli-user:cli-pass@cli-proxy:9999"


def test_resolve_proxy_config_env_wins_when_cli_is_none(monkeypatch):
    monkeypatch.setenv("MCP_PROXY_URL", "http://env-proxy:8888")
    monkeypatch.setenv("MCP_PROXY_USERNAME", "env-user")
    monkeypatch.setenv("MCP_PROXY_PASSWORD", "env-pass")

    result = _resolve_proxy_config(None, None, None)

    assert result == "http://env-user:env-pass@env-proxy:8888"


def test_resolve_proxy_config_fields_resolve_independently(monkeypatch):
    monkeypatch.setenv("MCP_PROXY_URL", "http://env-proxy:8888")
    monkeypatch.delenv("MCP_PROXY_USERNAME", raising=False)
    monkeypatch.delenv("MCP_PROXY_PASSWORD", raising=False)

    result = _resolve_proxy_config(None, "cli-user", None)

    assert result == "http://cli-user@env-proxy:8888"


def test_resolve_proxy_config_returns_none_without_url(monkeypatch):
    monkeypatch.delenv("MCP_PROXY_URL", raising=False)

    result = _resolve_proxy_config(None, None, None)

    assert result is None


def test_build_proxy_url_without_username():
    assert _build_proxy_url("http://proxy:8888", None, None) == "http://proxy:8888"


def test_build_proxy_url_with_username_and_password():
    result = _build_proxy_url("http://proxy:8888", "user", "pass")

    assert result == "http://user:pass@proxy:8888"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv --directory packages/mcp-recipe-scraper run pytest tests/test_proxy.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name '_build_proxy_url'`.

- [ ] **Step 4: Replace `_proxy_url()` with `_resolve_proxy_config()` + `_build_proxy_url()`, and add the CLI flags**

In `packages/mcp-recipe-scraper/src/mcp_recipe_scraper/__main__.py`, replace the existing block (the `_proxy_url()` function definition through the `PROXY = _proxy_url()` line, currently lines 31-56) with the same replacement used in Task 1 Step 4:

```python
PROXY: str | None = None


def _resolve_proxy_config(
    cli_url: str | None, cli_username: str | None, cli_password: str | None
) -> str | None:
    """Merge CLI proxy args with MCP_PROXY_* env vars, CLI winning per field."""
    url = cli_url if cli_url is not None else os.environ.get("MCP_PROXY_URL")
    if not url:
        return None
    username = cli_username if cli_username is not None else os.environ.get("MCP_PROXY_USERNAME")
    password = cli_password if cli_password is not None else os.environ.get("MCP_PROXY_PASSWORD")
    return _build_proxy_url(url, username, password)


def _build_proxy_url(url: str, username: str | None, password: str | None) -> str:
    """Embed Basic auth userinfo into a proxy URL, if a username is given."""
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

Then update `main()`, replacing its body with the same shape as Task 1 Step 4 (prog name stays `"mcp-recipe-scraper"`):

```python
def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-recipe-scraper")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to serve over (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (streamable-http only)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (streamable-http only)")
    parser.add_argument("--path", default="/mcp", help="HTTP path for the MCP endpoint (streamable-http only)")
    parser.add_argument(
        "--proxy-url",
        default=None,
        help="Proxy endpoint for outbound requests, e.g. http://tinyproxy-host:8888 (overrides MCP_PROXY_URL)",
    )
    parser.add_argument(
        "--proxy-username",
        default=None,
        help="Basic auth username for the proxy (overrides MCP_PROXY_USERNAME)",
    )
    parser.add_argument(
        "--proxy-password",
        default=None,
        help="Basic auth password for the proxy (overrides MCP_PROXY_PASSWORD)",
    )
    args = parser.parse_args()

    global PROXY
    PROXY = _resolve_proxy_config(args.proxy_url, args.proxy_username, args.proxy_password)

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()
```

`scrape_recipe()` itself is untouched in this task.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv --directory packages/mcp-recipe-scraper run pytest tests/test_proxy.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add packages/mcp-recipe-scraper/pyproject.toml packages/mcp-recipe-scraper/src/mcp_recipe_scraper/__main__.py packages/mcp-recipe-scraper/tests/test_proxy.py
git commit -m "feat(mcp-recipe-scraper): add CLI proxy params with per-field precedence over env"
```

---

### Task 4: mcp-recipe-scraper — direct-request fallback

**Files:**
- Modify: `packages/mcp-recipe-scraper/src/mcp_recipe_scraper/__main__.py`
- Modify: `packages/mcp-recipe-scraper/tests/test_proxy.py`

**Interfaces:**
- Consumes: `PROXY: str | None`, `_resolve_proxy_config` (Task 3).
- Produces: `_env_flag(name: str) -> bool`, `_fetch(url: str) -> tuple[httpx.Response, bool]`, module-level `PROXY_FALLBACK: bool`, `PROXY_FALLBACK_TIMEOUT = 10.0`, `NOTE_PROXY_FALLBACK: str` — identical contracts to Task 2's, duplicated in this package.

- [ ] **Step 1: Write the failing tests**

Append to `packages/mcp-recipe-scraper/tests/test_proxy.py` (add these imports at the top, alongside the existing ones):

```python
import asyncio

import httpx
import pytest

import mcp_recipe_scraper.__main__ as main_mod
from mcp_recipe_scraper.__main__ import _env_flag, _fetch, scrape_recipe
```

Append these test functions to the file:

```python
def test_env_flag_true_values(monkeypatch):
    for value in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv("MCP_PROXY_FALLBACK", value)
        assert _env_flag("MCP_PROXY_FALLBACK") is True


def test_env_flag_false_when_unset(monkeypatch):
    monkeypatch.delenv("MCP_PROXY_FALLBACK", raising=False)
    assert _env_flag("MCP_PROXY_FALLBACK") is False


class _FakeAsyncClient:
    """Records the proxy it was constructed with and delegates .get() to a callback."""

    def __init__(self, get_impl, follow_redirects=True, timeout=None, proxy=None):
        self.proxy = proxy
        self._get_impl = get_impl

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, headers=None):
        return await self._get_impl(self.proxy, url)


def test_fetch_uses_proxy_when_fallback_disabled(monkeypatch):
    monkeypatch.setattr(main_mod, "PROXY", "http://proxy:8888")
    monkeypatch.setattr(main_mod, "PROXY_FALLBACK", False)
    seen_proxies = []

    async def get_impl(proxy, url):
        seen_proxies.append(proxy)
        return httpx.Response(200, request=httpx.Request("GET", url), text="ok")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(get_impl, **kw))

    response, used_fallback = asyncio.run(_fetch("http://example.com"))

    assert used_fallback is False
    assert response.text == "ok"
    assert seen_proxies == ["http://proxy:8888"]


def test_fetch_falls_back_on_connect_error(monkeypatch):
    monkeypatch.setattr(main_mod, "PROXY", "http://proxy:8888")
    monkeypatch.setattr(main_mod, "PROXY_FALLBACK", True)
    seen_proxies = []

    async def get_impl(proxy, url):
        seen_proxies.append(proxy)
        if proxy:
            raise httpx.ConnectError("boom", request=httpx.Request("GET", url))
        return httpx.Response(200, request=httpx.Request("GET", url), text="direct ok")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(get_impl, **kw))

    response, used_fallback = asyncio.run(_fetch("http://example.com"))

    assert used_fallback is True
    assert response.text == "direct ok"
    assert seen_proxies == ["http://proxy:8888", None]


def test_fetch_does_not_fall_back_on_http_status_error(monkeypatch):
    monkeypatch.setattr(main_mod, "PROXY", "http://proxy:8888")
    monkeypatch.setattr(main_mod, "PROXY_FALLBACK", True)
    call_count = 0

    async def get_impl(proxy, url):
        nonlocal call_count
        call_count += 1
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(get_impl, **kw))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_fetch("http://example.com"))

    assert call_count == 1


class _FakeScraper:
    def title(self):
        return "Test Recipe"

    def yields(self):
        return "4 servings"

    def ingredients(self):
        return ["a", "b"]

    def instructions(self):
        return "Do it"

    def nutrients(self):
        return {"calories": "100"}

    def to_json(self):
        return {"title": "Test Recipe"}


def test_scrape_recipe_prepends_note_when_fallback_used(monkeypatch):
    async def fake_fetch(url):
        return httpx.Response(200, request=httpx.Request("GET", url), text="<html></html>"), True

    monkeypatch.setattr(main_mod, "_fetch", fake_fetch)
    monkeypatch.setattr(main_mod, "scrape_html", lambda html, org_url, supported_only: _FakeScraper())

    result = asyncio.run(scrape_recipe(url="http://example.com", supported_only=False))

    assert result.startswith("> Note: the proxy did not respond")
    assert "Test Recipe" in result


def test_scrape_recipe_no_note_without_fallback(monkeypatch):
    async def fake_fetch(url):
        return httpx.Response(200, request=httpx.Request("GET", url), text="<html></html>"), False

    monkeypatch.setattr(main_mod, "_fetch", fake_fetch)
    monkeypatch.setattr(main_mod, "scrape_html", lambda html, org_url, supported_only: _FakeScraper())

    result = asyncio.run(scrape_recipe(url="http://example.com", supported_only=False))

    assert not result.startswith("> Note:")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv --directory packages/mcp-recipe-scraper run pytest tests/test_proxy.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name '_env_flag'`.

- [ ] **Step 3: Add `sys` import, the fallback globals, `_env_flag`, `_fetch`, and the `--proxy-fallback` flag**

In `packages/mcp-recipe-scraper/src/mcp_recipe_scraper/__main__.py`, add `import sys` to the top import block.

Replace the `PROXY: str | None = None` line (added in Task 3) with:

```python
PROXY: str | None = None
PROXY_FALLBACK = False
PROXY_FALLBACK_TIMEOUT = 10.0
NOTE_PROXY_FALLBACK = "> Note: the proxy did not respond; this request was sent directly (no proxy)."
```

Add `_env_flag` and `_fetch` right after `_build_proxy_url`'s definition (identical to Task 2 Step 3):

```python
def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def _fetch(url: str) -> tuple[httpx.Response, bool]:
    """GET url, honoring PROXY/PROXY_FALLBACK. Returns (response, used_fallback)."""
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

Add the `--proxy-fallback` flag in `main()`, right after the `--proxy-password` argument, and update the resolution lines — identical to Task 2 Step 3:

```python
    parser.add_argument(
        "--proxy-fallback",
        action="store_true",
        help="Fall back to a direct request if the proxy doesn't respond (or set MCP_PROXY_FALLBACK)",
    )
```

```python
    global PROXY, PROXY_FALLBACK
    PROXY = _resolve_proxy_config(args.proxy_url, args.proxy_username, args.proxy_password)
    PROXY_FALLBACK = args.proxy_fallback or _env_flag("MCP_PROXY_FALLBACK")
```

- [ ] **Step 4: Wire `scrape_recipe()` to use `_fetch()` and prepend the note**

Replace the body of `scrape_recipe()` up through `html = response.text` (currently the `async with httpx.AsyncClient(...)` block) with:

```python
    response, used_fallback = await _fetch(url)
    html = response.text
```

And update the final two lines of the function (the `lines += ["## Raw JSON", ...]` line through `return "\n".join(lines)`):

```python
    lines += ["## Raw JSON", "```json", json.dumps(data, indent=2, ensure_ascii=False), "```"]

    if used_fallback:
        lines.insert(0, NOTE_PROXY_FALLBACK)
        lines.insert(1, "")

    return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv --directory packages/mcp-recipe-scraper run pytest tests/test_proxy.py -v`
Expected: PASS (13 tests: 6 from Task 3 + 7 new)

- [ ] **Step 6: Commit**

```bash
git add packages/mcp-recipe-scraper/src/mcp_recipe_scraper/__main__.py packages/mcp-recipe-scraper/tests/test_proxy.py
git commit -m "feat(mcp-recipe-scraper): fall back to a direct request when the proxy doesn't respond"
```

---

### Task 5: Documentation — README and .env.example updates

**Files:**
- Modify: `README.md`
- Modify: `packages/mcp-fetch-select/.env.example`
- Modify: `packages/mcp-recipe-scraper/.env.example`

**Interfaces:**
- Consumes: flag/env names from Tasks 1-4 (`--proxy-url`/`--proxy-username`/`--proxy-password`/`--proxy-fallback`, `MCP_PROXY_FALLBACK`). No code interfaces produced — this task is documentation-only, verified by manual review rather than a test run.

- [ ] **Step 1: Update the README's "Proxying outbound requests" section**

In `README.md`, replace the section from the `## Proxying outbound requests` heading through the line before the next `---` (currently lines 100-131) with:

```markdown
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
```

(Keep the `---` that follows this section, marking the start of "Adding a new package".)

- [ ] **Step 2: Update `packages/mcp-fetch-select/.env.example`**

Append to `packages/mcp-fetch-select/.env.example`:

```
# Fall back to a direct request if the proxy doesn't respond.
#MCP_PROXY_FALLBACK=1
```

- [ ] **Step 3: Update `packages/mcp-recipe-scraper/.env.example`**

Append to `packages/mcp-recipe-scraper/.env.example`:

```
# Fall back to a direct request if the proxy doesn't respond.
#MCP_PROXY_FALLBACK=1
```

- [ ] **Step 4: Review the rendered README section**

Run: `git diff README.md`
Expected: the new table has three columns (env var / CLI flag / purpose), both example commands are present, and the new "Falling back to a direct request" subsection reads correctly before the `---` separator.

- [ ] **Step 5: Commit**

```bash
git add README.md packages/mcp-fetch-select/.env.example packages/mcp-recipe-scraper/.env.example
git commit -m "docs: document proxy CLI flags and MCP_PROXY_FALLBACK"
```
