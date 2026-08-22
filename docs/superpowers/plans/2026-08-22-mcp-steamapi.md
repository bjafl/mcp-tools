# mcp-steamapi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `mcp-steamapi`, a new MCP server package exposing 16 tools over the Steam Web API (achievement mapping, library/playtime, profile/social, store metadata).

**Architecture:** New standalone package under `packages/mcp-steamapi/`, following `mcp-openlibrary`'s shape (argparse CLI, `MCPServer` app, `src/` layout split into `normalize.py`/`ratelimit.py`/`cache.py`/`client.py`) but with two rate-limited hosts and a richer per-endpoint error-handling scheme instead of one 404→`None` sentinel.

**Tech Stack:** Python 3.12+, `mcp[cli]`, `httpx` (async), `pydantic`, `pytest` + `monkeypatch` (no live network calls, no real sleeping in tests).

**Spec:** `docs/superpowers/specs/2026-08-22-mcp-steamapi-design.md`

## Global Constraints

- Python `>=3.12`, `uv_build` backend, `src/` layout, `[project.scripts] mcp-steamapi = "mcp_steamapi:main"` — same shape as `mcp-openlibrary`/`mcp-recipe-scraper`.
- Dependencies: `mcp[cli]>=2.0.0,<3`, `httpx>=0.27,<0.29`, `pydantic>=2,<3`. No new libraries.
- `STEAM_API_KEY` env var only — no CLI flag, no proxy support (spec §"API key"/§9).
- `TokenBucket.acquire()` is `async def` using `await asyncio.sleep(...)` from the start — **never** `time.sleep()` in any async code path (this is the exact bug `mcp-openlibrary`'s final review caught and fixed after the fact; here it must be correct from Task 3 onward).
- Caching is in-memory only (`TTLCache`, no disk) and used **only** for `GetSchemaForGame` and `GetAppList` — every other endpoint is fetched fresh every call.
- `RETRY_STATUS_CODES = {429, 500, 502, 503, 504}`; a plain `400` is never retried (spec §6's note — it's a normal "no achievements"/"invalid appid" outcome, not a transient failure).
- `SteamClient._get()` raises `SteamAPIError` only for genuinely fatal cases (403 + non-JSON body = bad key; retries exhausted; unexpected non-JSON content-type). A `403` + JSON body (private profile) is returned as data, not raised — the calling tool interprets the JSON shape itself.
- Every tool validates `steamid` via `is_valid_steamid64()` before making any HTTP call, where the tool takes a `steamid` parameter.
- `get_player_summary`/`get_player_bans` accept a single `steamid` only in v1 — no comma-separated batch (spec §9, explicitly out of scope).
- `CLIENT` global must be safely accessible via a `_client()` helper that lazily constructs it if `None`, not referenced directly by tool functions — this is the exact class of bug `mcp-openlibrary`'s final review also caught (tools crashing with an opaque `AttributeError` if `app` is imported without going through this package's own `main()`). Build it correctly from Task 6 onward.
- No test in this plan makes a live network call; every rate-limit/retry test patches `asyncio.sleep` (never `time.sleep`).
- When staging files for commit, stage by exact filename (`git add <file> <file>`) — never `git add -A`/`git add .`.

---

### Task 1: Package scaffolding

**Files:**
- Create: `packages/mcp-steamapi/pyproject.toml`
- Create: `packages/mcp-steamapi/src/mcp_steamapi/__init__.py`
- Create: `packages/mcp-steamapi/src/mcp_steamapi/__main__.py`
- Modify: `pyproject.toml` (repo root)
- Modify: `README.md` (repo root)

**Interfaces:**
- Produces: `mcp_steamapi.__main__.app` (an `MCPServer` instance), `mcp_steamapi.__main__.main() -> None`, `mcp_steamapi.main` (re-exported), the `mcp-steamapi` console script.

- [ ] **Step 1: Create `packages/mcp-steamapi/pyproject.toml`**

```toml
[project]
name = "mcp-steamapi"
version = "0.1.0"
description = "MCP server for the Steam Web API (achievements, library, profile, store metadata)"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=2.0.0,<3",
    "httpx>=0.27,<0.29",
    "pydantic>=2,<3",
]

[project.scripts]
mcp-steamapi = "mcp_steamapi:main"

[build-system]
requires = ["uv_build>=0.11.13,<0.12"]
build-backend = "uv_build"

[tool.hatch.build.targets.wheel]
packages = ["src/mcp_steamapi"]

[dependency-groups]
dev = ["pytest>=8,<9"]
```

- [ ] **Step 2: Create `packages/mcp-steamapi/src/mcp_steamapi/__init__.py`**

```python
from mcp_steamapi.__main__ import main

__all__ = ["main"]
```

- [ ] **Step 3: Create `packages/mcp-steamapi/src/mcp_steamapi/__main__.py`** (transport-only skeleton; API key/CLIENT wiring and tools land in later tasks)

```python
import argparse

from mcp.server.mcpserver import MCPServer

app = MCPServer("mcp-steamapi")


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-steamapi")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to serve over (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (streamable-http only)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (streamable-http only)")
    parser.add_argument("--path", default="/mcp", help="HTTP path for the MCP endpoint (streamable-http only)")
    args = parser.parse_args()

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Wire the package into the root workspace**

In `pyproject.toml` (repo root), add `mcp-steamapi` to `dependencies` and `[tool.uv.sources]`:

```toml
[project]
name = "mcp-tools"
version = "0.1.0"
description = "MCP server collection"
requires-python = ">=3.12"
dependencies = [
  "mcp-fetch-select", "mcp-recipe-scraper", "mcp-openlibrary", "mcp-steamapi",
]

[tool.uv.sources]
mcp-fetch-select = { workspace = true }
mcp-recipe-scraper = { workspace = true }
mcp-openlibrary = { workspace = true }
mcp-steamapi = { workspace = true }

[tool.uv.workspace]
members = ["packages/*"]

[tool.pytest.ini_options]
addopts = "--import-mode=importlib"
```

- [ ] **Step 5: Add a row to the package table in `README.md`**

In the `## Packages` table, add:

```markdown
| [mcp-steamapi](packages/mcp-steamapi/) | Steam Web API: achievements, library/playtime, profile/social, store metadata |
```

- [ ] **Step 6: Verify the package installs and runs**

Run:
```bash
uv sync
uv run --directory packages/mcp-steamapi mcp-steamapi --help
```
Expected: `uv sync` succeeds; `--help` prints usage including `--transport`/`--host`/`--port`/`--path`. No `tests/` directory exists yet — Task 2 creates it.

- [ ] **Step 7: Commit**

```bash
git add packages/mcp-steamapi/pyproject.toml packages/mcp-steamapi/src/mcp_steamapi/__init__.py packages/mcp-steamapi/src/mcp_steamapi/__main__.py pyproject.toml README.md
git commit -m "feat(mcp-steamapi): scaffold new package"
```

---

### Task 2: `normalize.py` — pure data-shape helpers

**Files:**
- Create: `packages/mcp-steamapi/src/mcp_steamapi/normalize.py`
- Test: `packages/mcp-steamapi/tests/test_normalize.py`

**Interfaces:**
- Produces: `is_valid_steamid64(steamid: str) -> bool`, `steam_icon_url(appid: int, img_icon_url: str) -> str`, `minutes_to_hours(minutes: int) -> float`, `visibility_label(state: int) -> str`, `persona_state_label(state: int) -> str`, `is_empty_owned_games_response(data: dict) -> bool`, `player_achievements_error(data: dict) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-steamapi/tests/test_normalize.py
import pytest

from mcp_steamapi.normalize import (
    is_valid_steamid64,
    steam_icon_url,
    minutes_to_hours,
    visibility_label,
    persona_state_label,
    is_empty_owned_games_response,
    player_achievements_error,
)


@pytest.mark.parametrize(
    "steamid,expected",
    [
        ("76561197960265728", True),
        ("7656119796026572", False),
        ("765611979602657289", False),
        ("abc", False),
        ("", False),
    ],
)
def test_is_valid_steamid64(steamid, expected):
    assert is_valid_steamid64(steamid) == expected


def test_steam_icon_url_builds_url():
    assert (
        steam_icon_url(620, "abc123hash")
        == "https://media.steampowered.com/steamcommunity/public/images/apps/620/abc123hash.jpg"
    )


@pytest.mark.parametrize("minutes,expected", [(60, 1.0), (90, 1.5), (0, 0.0), (1843, 30.7)])
def test_minutes_to_hours(minutes, expected):
    assert minutes_to_hours(minutes) == expected


@pytest.mark.parametrize("state,expected", [(1, "private/friends only"), (3, "public"), (99, "unknown")])
def test_visibility_label(state, expected):
    assert visibility_label(state) == expected


@pytest.mark.parametrize(
    "state,expected",
    [
        (0, "Offline"),
        (1, "Online"),
        (2, "Busy"),
        (3, "Away"),
        (4, "Snooze"),
        (5, "Looking to trade"),
        (6, "Looking to play"),
        (99, "Unknown"),
    ],
)
def test_persona_state_label(state, expected):
    assert persona_state_label(state) == expected


def test_is_empty_owned_games_response_true_when_no_games_key():
    assert is_empty_owned_games_response({"response": {}}) is True


def test_is_empty_owned_games_response_false_when_games_present():
    assert is_empty_owned_games_response({"response": {"game_count": 0, "games": []}}) is False


def test_player_achievements_error_returns_message_on_failure():
    data = {"playerstats": {"error": "Profile is not public", "success": False}}
    assert player_achievements_error(data) == "Profile is not public"


def test_player_achievements_error_returns_default_message_when_error_missing():
    data = {"playerstats": {"success": False}}
    assert player_achievements_error(data) == "Steam reported an error for this request."


def test_player_achievements_error_none_on_success():
    data = {"playerstats": {"success": True, "achievements": []}}
    assert player_achievements_error(data) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-steamapi/tests/test_normalize.py -v`
Expected: FAIL/ERROR — `mcp_steamapi.normalize` doesn't exist yet.

- [ ] **Step 3: Write `normalize.py`**

```python
# packages/mcp-steamapi/src/mcp_steamapi/normalize.py

def is_valid_steamid64(steamid: str) -> bool:
    """SteamID64 is a 17-digit decimal string."""
    return steamid.isdigit() and len(steamid) == 17


def steam_icon_url(appid: int, img_icon_url: str) -> str:
    return f"https://media.steampowered.com/steamcommunity/public/images/apps/{appid}/{img_icon_url}.jpg"


def minutes_to_hours(minutes: int) -> float:
    return round(minutes / 60, 1)


_VISIBILITY_LABELS = {1: "private/friends only", 3: "public"}


def visibility_label(state: int) -> str:
    return _VISIBILITY_LABELS.get(state, "unknown")


_PERSONA_STATE_LABELS = {
    0: "Offline",
    1: "Online",
    2: "Busy",
    3: "Away",
    4: "Snooze",
    5: "Looking to trade",
    6: "Looking to play",
}


def persona_state_label(state: int) -> str:
    return _PERSONA_STATE_LABELS.get(state, "Unknown")


def is_empty_owned_games_response(data: dict) -> bool:
    """Detect GetOwnedGames' silent-private shape: {"response": {}} with no "games" key."""
    return "games" not in data.get("response", {})


def player_achievements_error(data: dict) -> str | None:
    """Given a GetPlayerAchievements response, return a human error message if the API
    reported failure (private profile, no stats for this app), else None on genuine success."""
    playerstats = data.get("playerstats", {})
    if playerstats.get("success") is False:
        return playerstats.get("error", "Steam reported an error for this request.")
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-steamapi/tests/test_normalize.py -v`
Expected: PASS (all tests green).

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-steamapi/src/mcp_steamapi/normalize.py packages/mcp-steamapi/tests/test_normalize.py
git commit -m "feat(mcp-steamapi): add normalize helpers"
```

---

### Task 3: `ratelimit.py` — async token bucket

**Files:**
- Create: `packages/mcp-steamapi/src/mcp_steamapi/ratelimit.py`
- Test: `packages/mcp-steamapi/tests/test_ratelimit.py`

**Interfaces:**
- Produces: `TokenBucket(rate_per_sec: float)` with `async def acquire() -> None` (awaits `asyncio.sleep(...)` until the next slot is available — **not** `time.sleep()`).

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-steamapi/tests/test_ratelimit.py
import asyncio

import mcp_steamapi.ratelimit as ratelimit_mod
from mcp_steamapi.ratelimit import TokenBucket


def test_first_acquire_does_not_sleep(monkeypatch):
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: 100.0)
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(ratelimit_mod.asyncio, "sleep", fake_sleep)

    bucket = TokenBucket(rate_per_sec=2.0)
    asyncio.run(bucket.acquire())

    assert sleeps == []


def test_second_acquire_sleeps_for_interval(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: clock["t"])
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(ratelimit_mod.asyncio, "sleep", fake_sleep)

    async def run_two():
        bucket = TokenBucket(rate_per_sec=2.0)  # 0.5s interval
        await bucket.acquire()
        await bucket.acquire()

    asyncio.run(run_two())

    assert sleeps == [0.5]


def test_acquire_does_not_sleep_if_enough_time_passed(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: clock["t"])
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(ratelimit_mod.asyncio, "sleep", fake_sleep)

    async def run_two():
        bucket = TokenBucket(rate_per_sec=2.0)
        await bucket.acquire()
        clock["t"] = 105.0
        await bucket.acquire()

    asyncio.run(run_two())

    assert sleeps == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-steamapi/tests/test_ratelimit.py -v`
Expected: FAIL/ERROR — `mcp_steamapi.ratelimit` doesn't exist yet.

- [ ] **Step 3: Write `ratelimit.py`**

```python
# packages/mcp-steamapi/src/mcp_steamapi/ratelimit.py
import asyncio
import time


class TokenBucket:
    """Async rate limiter: acquire() awaits until the next slot is available.

    No lock: there is no `await` between reading and writing `self._next`, so a
    single-threaded asyncio event loop cannot interleave two callers mid-update.
    """

    def __init__(self, rate_per_sec: float):
        self._interval = 1.0 / rate_per_sec
        self._next = 0.0

    async def acquire(self) -> None:
        now = time.monotonic()
        wait = max(0.0, self._next - now)
        self._next = max(now, self._next) + self._interval
        if wait:
            await asyncio.sleep(wait)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-steamapi/tests/test_ratelimit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-steamapi/src/mcp_steamapi/ratelimit.py packages/mcp-steamapi/tests/test_ratelimit.py
git commit -m "feat(mcp-steamapi): add async TokenBucket rate limiter"
```

---

### Task 4: `cache.py` — in-memory TTL cache

**Files:**
- Create: `packages/mcp-steamapi/src/mcp_steamapi/cache.py`
- Test: `packages/mcp-steamapi/tests/test_cache.py`

**Interfaces:**
- Produces: `TTLCache(ttl_seconds: float)` with `.get(key: str) -> object | None` and `.set(key: str, value: object) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-steamapi/tests/test_cache.py
import mcp_steamapi.cache as cache_mod
from mcp_steamapi.cache import TTLCache


def test_get_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: 100.0)
    cache = TTLCache(ttl_seconds=10)

    assert cache.get("k") is None


def test_get_returns_value_before_expiry(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock["t"])
    cache = TTLCache(ttl_seconds=10)

    cache.set("k", "v")
    clock["t"] = 105.0

    assert cache.get("k") == "v"


def test_get_returns_none_after_expiry(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock["t"])
    cache = TTLCache(ttl_seconds=10)

    cache.set("k", "v")
    clock["t"] = 111.0

    assert cache.get("k") is None


def test_expired_entry_is_evicted_from_store(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock["t"])
    cache = TTLCache(ttl_seconds=10)

    cache.set("k", "v")
    clock["t"] = 111.0
    cache.get("k")

    assert "k" not in cache._store
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-steamapi/tests/test_cache.py -v`
Expected: FAIL/ERROR — `mcp_steamapi.cache` doesn't exist yet.

- [ ] **Step 3: Write `cache.py`**

```python
# packages/mcp-steamapi/src/mcp_steamapi/cache.py
import time


class TTLCache:
    """Simple in-memory cache with per-entry TTL. No disk persistence."""

    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, object]] = {}

    def get(self, key: str) -> object | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: object) -> None:
        self._store[key] = (time.monotonic() + self._ttl, value)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-steamapi/tests/test_cache.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-steamapi/src/mcp_steamapi/cache.py packages/mcp-steamapi/tests/test_cache.py
git commit -m "feat(mcp-steamapi): add in-memory TTLCache"
```

---

### Task 5: `client.py` — HTTP layer with two rate-limited hosts

**Files:**
- Create: `packages/mcp-steamapi/src/mcp_steamapi/client.py`
- Test: `packages/mcp-steamapi/tests/test_client.py`

**Interfaces:**
- Consumes: `TokenBucket` from `mcp_steamapi.ratelimit` (Task 3).
- Produces: `SteamAPIError(message: str, status_code: int | None = None)`, `SteamClient(api_key: str, api_rate: float = 5.0, store_rate: float = 0.5)` with `async def get_api(interface_path: str, needs_key: bool = True, **params) -> dict`, `async def get_store(path: str, **params) -> dict`, `async def aclose() -> None`; module constants `API_BASE`, `STORE_BASE`, `RETRY_STATUS_CODES`, `MAX_ATTEMPTS`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-steamapi/tests/test_client.py
import asyncio

import httpx
import pytest

import mcp_steamapi.client as client_mod
import mcp_steamapi.ratelimit as ratelimit_mod
from mcp_steamapi.client import SteamAPIError, SteamClient


class _FakeResponse:
    def __init__(self, status_code, json_data=None, content_type="application/json", empty=False, headers=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.headers = {"content-type": content_type, **(headers or {})}
        self.content = b"" if empty else b"non-empty"

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, get_impl):
        self._get_impl = get_impl
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append((url, params))
        return await self._get_impl(url, params)


def _make_client(monkeypatch, get_impl, sleeps=None, api_rate=1000.0, store_rate=1000.0):
    fake = _FakeAsyncClient(get_impl)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)

    async def fake_sleep(s):
        if sleeps is not None:
            sleeps.append(s)

    monkeypatch.setattr(ratelimit_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(client_mod.asyncio, "sleep", fake_sleep)
    return SteamClient(api_key="test-key", api_rate=api_rate, store_rate=store_rate), fake


def test_get_api_returns_data_on_200(monkeypatch):
    async def get_impl(url, params):
        return _FakeResponse(200, {"ok": True})

    client, fake = _make_client(monkeypatch, get_impl)

    result = asyncio.run(client.get_api("ISteamUser/GetPlayerSummaries/v2", steamids="123"))

    assert result == {"ok": True}


def test_get_api_injects_key_when_needed(monkeypatch):
    async def get_impl(url, params):
        return _FakeResponse(200, {"ok": True})

    client, fake = _make_client(monkeypatch, get_impl)

    asyncio.run(client.get_api("ISteamUser/GetPlayerSummaries/v2", steamids="123"))

    assert fake.calls[0][1]["key"] == "test-key"


def test_get_api_omits_key_when_not_needed(monkeypatch):
    async def get_impl(url, params):
        return _FakeResponse(200, {"ok": True})

    client, fake = _make_client(monkeypatch, get_impl)

    asyncio.run(
        client.get_api(
            "ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2", needs_key=False, gameid=620
        )
    )

    assert "key" not in fake.calls[0][1]


def test_get_api_omits_none_params(monkeypatch):
    async def get_impl(url, params):
        return _FakeResponse(200, {"ok": True})

    client, fake = _make_client(monkeypatch, get_impl)

    asyncio.run(client.get_api("ISteamUserStats/GetSchemaForGame/v2", appid=620, l=None))

    assert "l" not in fake.calls[0][1]
    assert fake.calls[0][1]["appid"] == 620


def test_get_api_raises_on_403_html_body(monkeypatch):
    async def get_impl(url, params):
        return _FakeResponse(403, content_type="text/html")

    client, fake = _make_client(monkeypatch, get_impl)

    with pytest.raises(SteamAPIError) as exc_info:
        asyncio.run(client.get_api("ISteamUser/GetPlayerSummaries/v2", steamids="123"))

    assert exc_info.value.status_code == 403
    assert "STEAM_API_KEY" in str(exc_info.value)


def test_get_api_passes_through_403_json_body(monkeypatch):
    async def get_impl(url, params):
        return _FakeResponse(403, {"playerstats": {"error": "Profile is not public", "success": False}})

    client, fake = _make_client(monkeypatch, get_impl)

    result = asyncio.run(
        client.get_api("ISteamUserStats/GetPlayerAchievements/v1", steamid="123", appid=620)
    )

    assert result == {"playerstats": {"error": "Profile is not public", "success": False}}


def test_get_api_does_not_retry_on_400(monkeypatch):
    calls = {"n": 0}

    async def get_impl(url, params):
        calls["n"] += 1
        return _FakeResponse(400, {"error": "no stats"})

    client, fake = _make_client(monkeypatch, get_impl)

    result = asyncio.run(
        client.get_api("ISteamUserStats/GetPlayerAchievements/v1", steamid="123", appid=620)
    )

    assert calls["n"] == 1
    assert result == {"error": "no stats"}


def test_get_api_retries_on_503_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get_impl(url, params):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResponse(503)
        return _FakeResponse(200, {"ok": True})

    client, fake = _make_client(monkeypatch, get_impl)

    result = asyncio.run(client.get_api("ISteamUser/GetPlayerSummaries/v2", steamids="123"))

    assert result == {"ok": True}
    assert calls["n"] == 3


def test_get_api_raises_after_max_attempts(monkeypatch):
    async def get_impl(url, params):
        return _FakeResponse(503)

    client, fake = _make_client(monkeypatch, get_impl)

    with pytest.raises(SteamAPIError):
        asyncio.run(client.get_api("ISteamUser/GetPlayerSummaries/v2", steamids="123"))


def test_get_api_retries_once_on_empty_body(monkeypatch):
    calls = {"n": 0}

    async def get_impl(url, params):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(200, empty=True)
        return _FakeResponse(200, {"ok": True})

    client, fake = _make_client(monkeypatch, get_impl)

    result = asyncio.run(client.get_api("ISteamUser/GetPlayerSummaries/v2", steamids="123"))

    assert result == {"ok": True}
    assert calls["n"] == 2


def test_get_api_respects_retry_after_header(monkeypatch):
    sleeps = []
    calls = {"n": 0}

    async def get_impl(url, params):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(429, headers={"retry-after": "3"})
        return _FakeResponse(200, {"ok": True})

    client, fake = _make_client(monkeypatch, get_impl, sleeps=sleeps)

    asyncio.run(client.get_api("ISteamUser/GetPlayerSummaries/v2", steamids="123"))

    assert 3.0 in sleeps


def test_get_store_hits_store_base_url(monkeypatch):
    async def get_impl(url, params):
        return _FakeResponse(200, {"ok": True})

    client, fake = _make_client(monkeypatch, get_impl)

    asyncio.run(client.get_store("/api/appdetails", appids=620))

    assert fake.calls[0][0] == "https://store.steampowered.com/api/appdetails"


def test_get_api_hits_api_base_url(monkeypatch):
    async def get_impl(url, params):
        return _FakeResponse(200, {"ok": True})

    client, fake = _make_client(monkeypatch, get_impl)

    asyncio.run(client.get_api("ISteamUser/GetPlayerSummaries/v2", steamids="123"))

    assert fake.calls[0][0] == "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-steamapi/tests/test_client.py -v`
Expected: FAIL/ERROR — `mcp_steamapi.client` doesn't exist yet.

- [ ] **Step 3: Write `client.py`**

```python
# packages/mcp-steamapi/src/mcp_steamapi/client.py
import asyncio

import httpx

from mcp_steamapi.ratelimit import TokenBucket

API_BASE = "https://api.steampowered.com"
STORE_BASE = "https://store.steampowered.com"
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5


class SteamAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SteamClient:
    def __init__(self, api_key: str, api_rate: float = 5.0, store_rate: float = 0.5):
        self._api_key = api_key
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True)
        self._api_bucket = TokenBucket(api_rate)
        self._store_bucket = TokenBucket(store_rate)

    async def get_api(self, interface_path: str, needs_key: bool = True, **params) -> dict:
        query = {"format": "json", **{k: v for k, v in params.items() if v is not None}}
        if needs_key:
            query["key"] = self._api_key
        return await self._get(f"{API_BASE}/{interface_path}/", query, self._api_bucket)

    async def get_store(self, path: str, **params) -> dict:
        query = {k: v for k, v in params.items() if v is not None}
        return await self._get(f"{STORE_BASE}{path}", query, self._store_bucket)

    async def _get(self, url: str, params: dict, bucket: TokenBucket) -> dict:
        for attempt in range(MAX_ATTEMPTS):
            await bucket.acquire()
            response = await self._http.get(url, params=params or None)

            if response.status_code in RETRY_STATUS_CODES:
                if attempt == MAX_ATTEMPTS - 1:
                    raise SteamAPIError(
                        f"Steam API error {response.status_code} after {MAX_ATTEMPTS} attempts",
                        response.status_code,
                    )
                await asyncio.sleep(_retry_delay(response, attempt))
                continue

            content_type = response.headers.get("content-type", "")
            if response.status_code == 403 and "application/json" not in content_type:
                raise SteamAPIError("Steam API rejected the request (403) — check STEAM_API_KEY", 403)

            if not response.content and attempt == 0:
                await asyncio.sleep(1.0)
                continue

            if "application/json" not in content_type:
                raise SteamAPIError(
                    f"Steam API returned non-JSON content ({content_type or 'unknown'})",
                    response.status_code,
                )

            try:
                return response.json()
            except ValueError as exc:
                raise SteamAPIError(f"Steam API returned invalid JSON: {exc}", response.status_code) from exc
        raise SteamAPIError(f"gave up after {MAX_ATTEMPTS} attempts: {url}")

    async def aclose(self) -> None:
        await self._http.aclose()


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return 2**attempt
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-steamapi/tests/test_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-steamapi/src/mcp_steamapi/client.py packages/mcp-steamapi/tests/test_client.py
git commit -m "feat(mcp-steamapi): add SteamClient HTTP layer"
```

---

### Task 6: `STEAM_API_KEY` wiring + `CLIENT` global

**Files:**
- Modify: `packages/mcp-steamapi/src/mcp_steamapi/__main__.py`
- Test: `packages/mcp-steamapi/tests/test_cli.py`

**Interfaces:**
- Consumes: `SteamClient` from `mcp_steamapi.client` (Task 5).
- Produces: `_resolve_api_key() -> str` (reads `STEAM_API_KEY`, calls `sys.exit(1)` with a clear stderr message if unset), module global `CLIENT: SteamClient | None = None`, `_client() -> SteamClient` (lazily constructs `CLIENT` if `None` — this is what every tool function calls, never `CLIENT` directly).

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-steamapi/tests/test_cli.py
import pytest

import mcp_steamapi.__main__ as main_mod
from mcp_steamapi.__main__ import _resolve_api_key, _client
from mcp_steamapi.client import SteamClient


def test_resolve_api_key_returns_env_value(monkeypatch):
    monkeypatch.setenv("STEAM_API_KEY", "abc123")
    assert _resolve_api_key() == "abc123"


def test_resolve_api_key_exits_when_unset(monkeypatch):
    monkeypatch.delenv("STEAM_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        _resolve_api_key()
    assert exc_info.value.code == 1


def test_client_lazily_constructs_when_none(monkeypatch):
    monkeypatch.setenv("STEAM_API_KEY", "abc123")
    monkeypatch.setattr(main_mod, "CLIENT", None)

    client = _client()

    assert isinstance(client, SteamClient)


def test_client_returns_existing_when_set(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(main_mod, "CLIENT", sentinel)

    result = _client()

    assert result is sentinel
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-steamapi/tests/test_cli.py -v`
Expected: FAIL — `_resolve_api_key`/`_client` don't exist yet.

- [ ] **Step 3: Update `__main__.py`**

Replace the full file with:

```python
# packages/mcp-steamapi/src/mcp_steamapi/__main__.py
import argparse
import os
import sys

from mcp.server.mcpserver import MCPServer

from mcp_steamapi.client import SteamClient

app = MCPServer("mcp-steamapi")

CLIENT: SteamClient | None = None


def _resolve_api_key() -> str:
    """Read STEAM_API_KEY from the environment. Exits with a clear error if unset."""
    key = os.environ.get("STEAM_API_KEY")
    if not key:
        print("STEAM_API_KEY environment variable is required but not set.", file=sys.stderr)
        sys.exit(1)
    return key


def _client() -> SteamClient:
    global CLIENT
    if CLIENT is None:
        CLIENT = SteamClient(api_key=_resolve_api_key())
    return CLIENT


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-steamapi")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to serve over (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (streamable-http only)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (streamable-http only)")
    parser.add_argument("--path", default="/mcp", help="HTTP path for the MCP endpoint (streamable-http only)")
    args = parser.parse_args()

    _client()  # fail fast if STEAM_API_KEY is missing, before serving any requests

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-steamapi/tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-steamapi/src/mcp_steamapi/__main__.py packages/mcp-steamapi/tests/test_cli.py
git commit -m "feat(mcp-steamapi): wire STEAM_API_KEY and lazy SteamClient into CLI"
```

---

### Task 7: Identity & library tools — `resolve_vanity_url`, `get_player_summary`, `get_owned_games`, `get_recently_played_games`

**Files:**
- Modify: `packages/mcp-steamapi/src/mcp_steamapi/__main__.py`
- Test: `packages/mcp-steamapi/tests/test_identity_library_tools.py`

**Interfaces:**
- Consumes: `_client()`/`app` from Task 6; `is_valid_steamid64`, `is_empty_owned_games_response`, `minutes_to_hours`, `visibility_label` from `mcp_steamapi.normalize` (Task 2).
- Produces: tool functions `resolve_vanity_url`, `get_player_summary`, `get_owned_games`, `get_recently_played_games`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-steamapi/tests/test_identity_library_tools.py
import asyncio

import mcp_steamapi.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get_api(self, interface_path, **params):
        self.calls.append((interface_path, params))
        return self.response


def test_resolve_vanity_url_returns_steamid(monkeypatch):
    fake = _FakeClient({"response": {"success": 1, "steamid": "76561197960265728"}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.resolve_vanity_url(vanity_url="gaben"))

    assert "76561197960265728" in result


def test_resolve_vanity_url_no_match(monkeypatch):
    fake = _FakeClient({"response": {"success": 42}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.resolve_vanity_url(vanity_url="zzznoexist"))

    assert "No SteamID64 match found" in result


def test_get_player_summary_returns_visibility(monkeypatch):
    fake = _FakeClient(
        {
            "response": {
                "players": [
                    {
                        "steamid": "76561197960265728",
                        "personaname": "Gaben",
                        "communityvisibilitystate": 3,
                        "profileurl": "https://x",
                    }
                ]
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_summary(steamid="76561197960265728"))

    assert "Gaben" in result
    assert "public" in result


def test_get_player_summary_flags_private_visibility(monkeypatch):
    fake = _FakeClient(
        {
            "response": {
                "players": [
                    {"steamid": "76561197960265728", "personaname": "Private Guy", "communityvisibilitystate": 1}
                ]
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_summary(steamid="76561197960265728"))

    assert "private/friends only" in result
    assert "will return empty or error" in result


def test_get_player_summary_rejects_invalid_steamid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_summary(steamid="not-a-steamid"))

    assert "not a valid SteamID64" in result
    assert fake.calls == []


def test_get_player_summary_not_found(monkeypatch):
    fake = _FakeClient({"response": {"players": []}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_summary(steamid="76561197960265728"))

    assert "No player found" in result


def test_get_owned_games_lists_games(monkeypatch):
    fake = _FakeClient(
        {
            "response": {
                "game_count": 1,
                "games": [
                    {"appid": 620, "name": "Portal 2", "playtime_forever": 1843, "has_community_visible_stats": True}
                ],
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_owned_games(steamid="76561197960265728"))

    assert "Portal 2" in result
    assert "620" in result
    assert "has stats/achievements" in result
    assert fake.calls[0][1]["include_appinfo"] == 1


def test_get_owned_games_private_response(monkeypatch):
    fake = _FakeClient({"response": {}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_owned_games(steamid="76561197960265728"))

    assert "not Public" in result


def test_get_owned_games_rejects_invalid_steamid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_owned_games(steamid="bad"))

    assert "not a valid SteamID64" in result
    assert fake.calls == []


def test_get_recently_played_games_lists_games(monkeypatch):
    fake = _FakeClient({"response": {"total_count": 1, "games": [{"appid": 620, "name": "Portal 2", "playtime_2weeks": 120}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_recently_played_games(steamid="76561197960265728"))

    assert "Portal 2" in result
    assert "2.0h" in result


def test_get_recently_played_games_empty(monkeypatch):
    fake = _FakeClient({"response": {"total_count": 0, "games": []}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_recently_played_games(steamid="76561197960265728"))

    assert "No recently played games" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-steamapi/tests/test_identity_library_tools.py -v`
Expected: FAIL — the 4 tool functions don't exist yet.

- [ ] **Step 3: Add imports and tool functions to `__main__.py`**

Add these imports near the top (alongside the existing ones from Task 6):

```python
import json
from typing import Annotated

from pydantic import Field

from mcp_steamapi.normalize import is_empty_owned_games_response, is_valid_steamid64, minutes_to_hours, visibility_label
```

Add the four tool functions, placed above `main()` (order in the file doesn't matter for `@app.tool`, but keep them grouped together):

```python
@app.tool(description="Resolve a Steam vanity URL name (steamcommunity.com/id/<name>) to a SteamID64.")
async def resolve_vanity_url(
    vanity_url: Annotated[str, Field(description="The name portion of steamcommunity.com/id/<name>")],
) -> str:
    data = await _client().get_api("ISteamUser/ResolveVanityURL/v1", vanityurl=vanity_url)
    response = data.get("response", {})
    if response.get("success") != 1:
        return f"No SteamID64 match found for vanity URL '{vanity_url}'."
    return f"SteamID64: {response['steamid']}"


@app.tool(description="Get a player's profile summary, including public visibility state (preflight check for other tools).")
async def get_player_summary(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("ISteamUser/GetPlayerSummaries/v2", steamids=steamid)
    players = data.get("response", {}).get("players", [])
    if not players:
        return f"No player found for SteamID64 '{steamid}'."

    player = players[0]
    visibility = visibility_label(player.get("communityvisibilitystate", 0))
    lines = [
        f"# {player.get('personaname', '(unknown)')}",
        f"**SteamID64:** {steamid}",
        f"**Profile visibility:** {visibility}",
        f"**Profile URL:** {player.get('profileurl', '')}",
    ]
    if visibility != "public":
        lines.append("")
        lines.append(
            "Note: game/achievement tools will return empty or error results for this player "
            "until their profile is set to Public."
        )
    lines += ["", "## Details", "```json", json.dumps(player, indent=2, ensure_ascii=False), "```"]
    return "\n".join(lines)


@app.tool(description="Get all games a player owns, with playtime. Requires 'Game details' to be Public.")
async def get_owned_games(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
    include_played_free_games: Annotated[
        bool, Field(description="Include free-to-play games the player has played")
    ] = False,
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api(
        "IPlayerService/GetOwnedGames/v1",
        steamid=steamid,
        include_appinfo=1,
        include_played_free_games=1 if include_played_free_games else None,
    )
    if is_empty_owned_games_response(data):
        return f"No owned games returned for '{steamid}' — profile or 'Game details' privacy setting is likely not Public."

    games = data.get("response", {}).get("games", [])
    lines = [f"# {len(games)} owned game(s) for {steamid}"]
    for game in games:
        hours = minutes_to_hours(game.get("playtime_forever", 0))
        stats_hint = " (has stats/achievements)" if game.get("has_community_visible_stats") else ""
        lines.append(f"- **{game.get('name', '(unknown)')}** — appid `{game.get('appid')}`, {hours}h played{stats_hint}")
    return "\n".join(lines)


@app.tool(description="Get a player's recently played games (last 2 weeks).")
async def get_recently_played_games(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
    count: Annotated[int, Field(description="Max games to return, 0 = all")] = 0,
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("IPlayerService/GetRecentlyPlayedGames/v1", steamid=steamid, count=count)
    games = data.get("response", {}).get("games", [])
    if not games:
        return f"No recently played games for '{steamid}'."

    lines = [f"# {len(games)} recently played game(s) for {steamid}"]
    for game in games:
        hours_2w = minutes_to_hours(game.get("playtime_2weeks", 0))
        lines.append(f"- **{game.get('name', '(unknown)')}** — appid `{game.get('appid')}`, {hours_2w}h in last 2 weeks")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-steamapi/tests/test_identity_library_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-steamapi/src/mcp_steamapi/__main__.py packages/mcp-steamapi/tests/test_identity_library_tools.py
git commit -m "feat(mcp-steamapi): add resolve_vanity_url, get_player_summary, get_owned_games, get_recently_played_games tools"
```

---

### Task 8: Achievement-join tools — `get_game_achievements_schema` (cached), `get_player_achievements`, `get_global_achievement_percentages`

**Files:**
- Modify: `packages/mcp-steamapi/src/mcp_steamapi/__main__.py`
- Test: `packages/mcp-steamapi/tests/test_achievements_join_tools.py`

**Interfaces:**
- Consumes: `_client()`/`app`/`is_valid_steamid64` from Tasks 6-7; `TTLCache` from `mcp_steamapi.cache` (Task 4); `player_achievements_error` from `mcp_steamapi.normalize` (Task 2).
- Produces: module global `_SCHEMA_CACHE: TTLCache`, `_schema_cache_key(appid: int, language: str | None) -> str`, tool functions `get_game_achievements_schema`, `get_player_achievements`, `get_global_achievement_percentages`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-steamapi/tests/test_achievements_join_tools.py
import asyncio

import mcp_steamapi.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get_api(self, interface_path, **params):
        self.calls.append((interface_path, params))
        return self.response


def test_get_game_achievements_schema_lists_achievements(monkeypatch):
    fake = _FakeClient(
        {
            "game": {
                "gameName": "Portal 2",
                "availableGameStats": {
                    "achievements": [
                        {"name": "ACH_1", "displayName": "Wake Up Call", "description": "Survive.", "hidden": 0}
                    ]
                },
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._SCHEMA_CACHE._store.clear()

    result = asyncio.run(main_mod.get_game_achievements_schema(appid=620))

    assert "Wake Up Call" in result
    assert "ACH_1" in result
    assert fake.calls[0][0] == "ISteamUserStats/GetSchemaForGame/v2"


def test_get_game_achievements_schema_no_achievements(monkeypatch):
    fake = _FakeClient({"game": {"gameName": "Tool App"}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._SCHEMA_CACHE._store.clear()

    result = asyncio.run(main_mod.get_game_achievements_schema(appid=1))

    assert "No achievements found" in result


def test_get_game_achievements_schema_caches_second_call(monkeypatch):
    fake = _FakeClient(
        {"game": {"gameName": "Portal 2", "availableGameStats": {"achievements": [{"name": "A", "displayName": "A"}]}}}
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._SCHEMA_CACHE._store.clear()

    asyncio.run(main_mod.get_game_achievements_schema(appid=620))
    asyncio.run(main_mod.get_game_achievements_schema(appid=620))

    assert len(fake.calls) == 1


def test_get_player_achievements_lists_status(monkeypatch):
    fake = _FakeClient(
        {
            "playerstats": {
                "success": True,
                "achievements": [
                    {"apiname": "ACH_1", "achieved": 1, "unlocktime": 1421070000, "name": "Wake Up Call"},
                    {"apiname": "ACH_2", "achieved": 0, "unlocktime": 0, "name": "Locked One"},
                ],
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_achievements(steamid="76561197960265728", appid=620))

    assert "1/2" in result
    assert "[unlocked]" in result
    assert "[locked]" in result


def test_get_player_achievements_private_profile(monkeypatch):
    fake = _FakeClient({"playerstats": {"error": "Profile is not public", "success": False}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_achievements(steamid="76561197960265728", appid=620))

    assert "Profile is not public" in result


def test_get_player_achievements_rejects_invalid_steamid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_achievements(steamid="bad", appid=620))

    assert "not a valid SteamID64" in result
    assert fake.calls == []


def test_get_global_achievement_percentages_lists_rarity(monkeypatch):
    fake = _FakeClient({"achievementpercentages": {"achievements": [{"name": "ACH_1", "percent": 96.4000015258789}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_global_achievement_percentages(appid=620))

    assert "96.4%" in result
    assert fake.calls[0][1]["gameid"] == 620
    assert fake.calls[0][1]["needs_key"] is False


def test_get_global_achievement_percentages_empty(monkeypatch):
    fake = _FakeClient({"achievementpercentages": {"achievements": []}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_global_achievement_percentages(appid=1))

    assert "No global achievement percentages" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-steamapi/tests/test_achievements_join_tools.py -v`
Expected: FAIL — the 3 tool functions don't exist yet.

- [ ] **Step 3: Add imports, cache global, and tool functions to `__main__.py`**

Task 7 left this single-line import:
```python
from mcp_steamapi.normalize import is_empty_owned_games_response, is_valid_steamid64, minutes_to_hours, visibility_label
```
**Replace that one line in place** (do not add a second, duplicate `from mcp_steamapi.normalize import ...` line anywhere in the file) with:

```python
from mcp_steamapi.normalize import (
    is_empty_owned_games_response,
    is_valid_steamid64,
    minutes_to_hours,
    player_achievements_error,
    visibility_label,
)
```

Add this new import:

```python
from mcp_steamapi.cache import TTLCache
```

Add the cache global and its key helper, placed after `CLIENT: SteamClient | None = None`:

```python
_SCHEMA_CACHE = TTLCache(ttl_seconds=7 * 24 * 3600)


def _schema_cache_key(appid: int, language: str | None) -> str:
    return f"{appid}:{language or ''}"
```

Add the three tool functions, grouped with the Task 7 tools above `main()`:

```python
@app.tool(description="Get all achievements available for a game (cached). Returns empty if the game has no achievements.")
async def get_game_achievements_schema(
    appid: Annotated[int, Field(description="Steam appid")],
    language: Annotated[str | None, Field(description="Language for displayName/description, e.g. 'norwegian'")] = None,
) -> str:
    cache_key = _schema_cache_key(appid, language)
    data = _SCHEMA_CACHE.get(cache_key)
    if data is None:
        data = await _client().get_api("ISteamUserStats/GetSchemaForGame/v2", appid=appid, l=language)
        _SCHEMA_CACHE.set(cache_key, data)

    game = data.get("game", {})
    achievements = game.get("availableGameStats", {}).get("achievements", [])
    if not achievements:
        return f"No achievements found for appid {appid} (this game may not have achievements)."

    lines = [f"# {len(achievements)} achievement(s) for {game.get('gameName', appid)} (appid {appid})"]
    for ach in achievements:
        hidden = " (hidden)" if ach.get("hidden") else ""
        lines.append(f"- `{ach['name']}` — **{ach.get('displayName', ach['name'])}**{hidden}: {ach.get('description', '')}")
    return "\n".join(lines)


@app.tool(description="Get a player's unlocked/locked achievements for a game.")
async def get_player_achievements(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
    appid: Annotated[int, Field(description="Steam appid")],
    language: Annotated[str | None, Field(description="Language for name/description, e.g. 'norwegian'")] = None,
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("ISteamUserStats/GetPlayerAchievements/v1", steamid=steamid, appid=appid, l=language)

    error = player_achievements_error(data)
    if error:
        return f"{error} (steamid {steamid}, appid {appid})"

    achievements = data.get("playerstats", {}).get("achievements", [])
    unlocked = [a for a in achievements if a.get("achieved") == 1]
    lines = [f"# {len(unlocked)}/{len(achievements)} achievement(s) unlocked for appid {appid}"]
    for ach in achievements:
        status = "unlocked" if ach.get("achieved") == 1 else "locked"
        unlock_note = f" (unlocked {ach['unlocktime']})" if ach.get("achieved") == 1 and ach.get("unlocktime") else ""
        lines.append(f"- [{status}] `{ach['apiname']}` — {ach.get('name', ach['apiname'])}{unlock_note}")
    return "\n".join(lines)


@app.tool(description="Get global unlock percentages (rarity) for a game's achievements. No API key needed.")
async def get_global_achievement_percentages(
    appid: Annotated[int, Field(description="Steam appid")],
) -> str:
    data = await _client().get_api(
        "ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2", needs_key=False, gameid=appid
    )
    achievements = data.get("achievementpercentages", {}).get("achievements", [])
    if not achievements:
        return f"No global achievement percentages found for appid {appid}."

    lines = [f"# Global achievement rarity for appid {appid}"]
    for ach in achievements:
        lines.append(f"- `{ach['name']}` — {round(ach['percent'], 1)}%")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-steamapi/tests/test_achievements_join_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-steamapi/src/mcp_steamapi/__main__.py packages/mcp-steamapi/tests/test_achievements_join_tools.py
git commit -m "feat(mcp-steamapi): add get_game_achievements_schema, get_player_achievements, get_global_achievement_percentages tools"
```

---

### Task 9: Stats & social tools — `get_user_stats_for_game`, `get_steam_level`, `get_badges`, `get_friend_list`, `get_player_bans`

**Files:**
- Modify: `packages/mcp-steamapi/src/mcp_steamapi/__main__.py`
- Test: `packages/mcp-steamapi/tests/test_stats_social_tools.py`

**Interfaces:**
- Consumes: `_client()`/`app`/`is_valid_steamid64` from Tasks 6-7.
- Produces: tool functions `get_user_stats_for_game`, `get_steam_level`, `get_badges`, `get_friend_list`, `get_player_bans`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-steamapi/tests/test_stats_social_tools.py
import asyncio

import mcp_steamapi.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get_api(self, interface_path, **params):
        self.calls.append((interface_path, params))
        return self.response


def test_get_user_stats_for_game_lists_stats(monkeypatch):
    fake = _FakeClient({"playerstats": {"stats": [{"name": "PORTALS_PLACED", "value": 3812}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_user_stats_for_game(steamid="76561197960265728", appid=620))

    assert "PORTALS_PLACED" in result
    assert "3812" in result


def test_get_user_stats_for_game_no_stats(monkeypatch):
    fake = _FakeClient({"playerstats": {}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_user_stats_for_game(steamid="76561197960265728", appid=620))

    assert "No stats found" in result


def test_get_steam_level_returns_level(monkeypatch):
    fake = _FakeClient({"response": {"player_level": 42}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_steam_level(steamid="76561197960265728"))

    assert "42" in result


def test_get_steam_level_rejects_invalid_steamid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_steam_level(steamid="bad"))

    assert "not a valid SteamID64" in result
    assert fake.calls == []


def test_get_badges_lists_badges(monkeypatch):
    fake = _FakeClient(
        {"response": {"badges": [{"badgeid": 1, "level": 2, "appid": 620}], "player_level": 10, "player_xp": 500}}
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_badges(steamid="76561197960265728"))

    assert "Badge `1`" in result
    assert "level 2" in result


def test_get_badges_no_badges(monkeypatch):
    fake = _FakeClient({"response": {"badges": [], "player_level": 0, "player_xp": 0}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_badges(steamid="76561197960265728"))

    assert "No badges found" in result


def test_get_friend_list_lists_friends(monkeypatch):
    fake = _FakeClient({"friendslist": {"friends": [{"steamid": "765611979", "friend_since": 1234567}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_friend_list(steamid="76561197960265728"))

    assert "765611979" in result
    assert fake.calls[0][1]["relationship"] == "friend"


def test_get_friend_list_empty(monkeypatch):
    fake = _FakeClient({"friendslist": {"friends": []}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_friend_list(steamid="76561197960265728"))

    assert "No public friend list found" in result


def test_get_player_bans_reports_status(monkeypatch):
    fake = _FakeClient(
        {
            "players": [
                {
                    "SteamId": "76561197960265728",
                    "VACBanned": False,
                    "NumberOfVACBans": 0,
                    "NumberOfGameBans": 0,
                    "CommunityBanned": False,
                    "EconomyBan": "none",
                    "DaysSinceLastBan": 0,
                }
            ]
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_bans(steamid="76561197960265728"))

    assert "VAC banned" in result
    assert fake.calls[0][1]["steamids"] == "76561197960265728"


def test_get_player_bans_not_found(monkeypatch):
    fake = _FakeClient({"players": []})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_player_bans(steamid="76561197960265728"))

    assert "No ban information found" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-steamapi/tests/test_stats_social_tools.py -v`
Expected: FAIL — the 5 tool functions don't exist yet.

- [ ] **Step 3: Add the five tool functions to `__main__.py`**

No new imports needed — this task reuses `Annotated`/`Field`/`is_valid_steamid64` already imported by Tasks 6-7. Add the five tool functions, grouped with the others above `main()`:

```python
@app.tool(
    description=(
        "Get a player's numeric stats for a game (e.g. progression counters). Achievements here "
        "lack unlocktime — prefer get_player_achievements for achievement status."
    )
)
async def get_user_stats_for_game(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
    appid: Annotated[int, Field(description="Steam appid")],
    language: Annotated[str | None, Field(description="Language, e.g. 'norwegian'")] = None,
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("ISteamUserStats/GetUserStatsForGame/v2", steamid=steamid, appid=appid, l=language)
    stats = data.get("playerstats", {}).get("stats", [])
    if not stats:
        return f"No stats found for steamid {steamid}, appid {appid}."

    lines = [f"# {len(stats)} stat(s) for appid {appid}"]
    for stat in stats:
        lines.append(f"- `{stat.get('name')}`: {stat.get('value')}")
    return "\n".join(lines)


@app.tool(description="Get a player's Steam level.")
async def get_steam_level(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("IPlayerService/GetSteamLevel/v1", steamid=steamid)
    level = data.get("response", {}).get("player_level")
    if level is None:
        return f"No Steam level found for '{steamid}'."
    return f"Steam level for {steamid}: {level}"


@app.tool(description="Get a player's badges and XP progress.")
async def get_badges(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("IPlayerService/GetBadges/v1", steamid=steamid)
    response = data.get("response", {})
    badges = response.get("badges", [])
    lines = [
        f"# Badges for {steamid}",
        f"**Level:** {response.get('player_level', '?')}, **XP:** {response.get('player_xp', '?')}",
        "",
    ]
    if not badges:
        lines.append("No badges found.")
    for badge in badges:
        appid_note = f", appid {badge['appid']}" if badge.get("appid") else ""
        lines.append(f"- Badge `{badge.get('badgeid')}` level {badge.get('level')}{appid_note}")
    return "\n".join(lines)


@app.tool(
    description=(
        "Get a player's friend list. Warning: comparing achievements across friends multiplies "
        "call volume by friends x games — this tool returns the raw list only, no batch comparison."
    )
)
async def get_friend_list(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("ISteamUser/GetFriendList/v1", steamid=steamid, relationship="friend")
    friends = data.get("friendslist", {}).get("friends", [])
    if not friends:
        return f"No public friend list found for '{steamid}'."

    lines = [f"# {len(friends)} friend(s) for {steamid}"]
    for friend in friends:
        lines.append(f"- `{friend.get('steamid')}` — friends since {friend.get('friend_since')}")
    return "\n".join(lines)


@app.tool(description="Get a player's VAC/game/community ban status.")
async def get_player_bans(
    steamid: Annotated[str, Field(description="SteamID64, 17-digit numeric string")],
) -> str:
    if not is_valid_steamid64(steamid):
        return f"'{steamid}' is not a valid SteamID64 (expected a 17-digit numeric string)."

    data = await _client().get_api("ISteamUser/GetPlayerBans/v1", steamids=steamid)
    players = data.get("players", [])
    if not players:
        return f"No ban information found for '{steamid}'."

    player = players[0]
    lines = [
        f"# Ban status for {steamid}",
        f"**VAC banned:** {player.get('VACBanned')} ({player.get('NumberOfVACBans', 0)} bans)",
        f"**Game banned:** {player.get('NumberOfGameBans', 0)} ban(s)",
        f"**Community banned:** {player.get('CommunityBanned')}",
        f"**Economy ban:** {player.get('EconomyBan')}",
        f"**Days since last ban:** {player.get('DaysSinceLastBan', '?')}",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-steamapi/tests/test_stats_social_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-steamapi/src/mcp_steamapi/__main__.py packages/mcp-steamapi/tests/test_stats_social_tools.py
git commit -m "feat(mcp-steamapi): add get_user_stats_for_game, get_steam_level, get_badges, get_friend_list, get_player_bans tools"
```

---

### Task 10: Store/metadata tools — `search_app_by_name` (cached), `get_current_player_count`, `get_app_details`, `get_app_reviews`

**Files:**
- Modify: `packages/mcp-steamapi/src/mcp_steamapi/__main__.py`
- Test: `packages/mcp-steamapi/tests/test_store_tools.py`

**Interfaces:**
- Consumes: `_client()`/`app` from Task 6; `TTLCache` from `mcp_steamapi.cache` (Task 4, already imported by Task 8).
- Produces: module global `_APPLIST_CACHE: TTLCache`, `_APPLIST_CACHE_KEY: str`, tool functions `search_app_by_name`, `get_current_player_count`, `get_app_details`, `get_app_reviews`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-steamapi/tests/test_store_tools.py
import asyncio

import mcp_steamapi.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get_api(self, interface_path, **params):
        self.calls.append((interface_path, params))
        return self.response

    async def get_store(self, path, **params):
        self.calls.append((path, params))
        return self.response


def test_search_app_by_name_finds_matches(monkeypatch):
    fake = _FakeClient({"applist": {"apps": [{"appid": 620, "name": "Portal 2"}, {"appid": 400, "name": "Portal"}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._APPLIST_CACHE._store.clear()

    result = asyncio.run(main_mod.search_app_by_name(query="portal"))

    assert "Portal 2" in result
    assert "620" in result


def test_search_app_by_name_caches_second_call(monkeypatch):
    fake = _FakeClient({"applist": {"apps": [{"appid": 620, "name": "Portal 2"}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._APPLIST_CACHE._store.clear()

    asyncio.run(main_mod.search_app_by_name(query="portal"))
    asyncio.run(main_mod.search_app_by_name(query="portal"))

    assert len(fake.calls) == 1


def test_search_app_by_name_no_matches(monkeypatch):
    fake = _FakeClient({"applist": {"apps": [{"appid": 620, "name": "Portal 2"}]}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)
    main_mod._APPLIST_CACHE._store.clear()

    result = asyncio.run(main_mod.search_app_by_name(query="zzznoexist"))

    assert "No apps found" in result


def test_get_current_player_count_returns_count(monkeypatch):
    fake = _FakeClient({"response": {"result": 1, "player_count": 12345}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_current_player_count(appid=620))

    assert "12345" in result


def test_get_current_player_count_not_found(monkeypatch):
    fake = _FakeClient({"response": {"result": 42}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_current_player_count(appid=999999))

    assert "No current player count" in result


def test_get_app_details_formats_summary(monkeypatch):
    fake = _FakeClient(
        {
            "620": {
                "success": True,
                "data": {
                    "name": "Portal 2",
                    "type": "game",
                    "is_free": False,
                    "price_overview": {"final": 1999, "currency": "NOK", "discount_percent": 50},
                    "genres": [{"description": "Action"}],
                },
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_app_details(appid=620))

    assert "Portal 2" in result
    assert "19.99" in result
    assert "Action" in result


def test_get_app_details_not_found(monkeypatch):
    fake = _FakeClient({"620": {"success": False}})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_app_details(appid=620))

    assert "No store details found" in result


def test_get_app_reviews_formats_summary(monkeypatch):
    fake = _FakeClient(
        {
            "query_summary": {
                "review_score_desc": "Overwhelmingly Positive",
                "total_positive": 1000,
                "total_negative": 10,
                "total_reviews": 1010,
            }
        }
    )
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_app_reviews(appid=620))

    assert "Overwhelmingly Positive" in result
    assert "1010" in result


def test_get_app_reviews_not_found(monkeypatch):
    fake = _FakeClient({})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_app_reviews(appid=620))

    assert "No review summary found" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-steamapi/tests/test_store_tools.py -v`
Expected: FAIL — the 4 tool functions don't exist yet.

- [ ] **Step 3: Add the AppList cache and four tool functions to `__main__.py`**

No new imports needed — `TTLCache` (Task 8), `json` (Task 7), and `Annotated`/`Field` (Task 7) are
already imported. Add the cache global, placed alongside `_SCHEMA_CACHE` (introduced by Task 8):

```python
_APPLIST_CACHE = TTLCache(ttl_seconds=7 * 24 * 3600)
_APPLIST_CACHE_KEY = "applist"
```

Add the four tool functions, grouped with the others above `main()`:

```python
@app.tool(
    description=(
        "Search the full Steam catalog by name substring to find an appid. "
        "First call after a cache miss is slow (the catalog is 200,000+ entries)."
    )
)
async def search_app_by_name(
    query: Annotated[str, Field(description="Name substring to search for, case-insensitive")],
    limit: Annotated[int, Field(description="Max matches to return, max 100")] = 10,
) -> str:
    limit = min(limit, 100)
    apps = _APPLIST_CACHE.get(_APPLIST_CACHE_KEY)
    if apps is None:
        data = await _client().get_api("ISteamApps/GetAppList/v2", needs_key=False)
        apps = data.get("applist", {}).get("apps", [])
        _APPLIST_CACHE.set(_APPLIST_CACHE_KEY, apps)

    query_lower = query.lower()
    matches = [app for app in apps if query_lower in app.get("name", "").lower()][:limit]
    if not matches:
        return f"No apps found matching '{query}'."

    lines = [f"# {len(matches)} match(es) for '{query}' (showing up to {limit})"]
    for app in matches:
        lines.append(f"- **{app.get('name')}** — appid `{app.get('appid')}`")
    return "\n".join(lines)


@app.tool(description="Get the current number of players in-game for an app. No API key needed.")
async def get_current_player_count(
    appid: Annotated[int, Field(description="Steam appid")],
) -> str:
    data = await _client().get_api("ISteamUserStats/GetNumberOfCurrentPlayers/v1", needs_key=False, appid=appid)
    response = data.get("response", {})
    if response.get("result") != 1:
        return f"No current player count available for appid {appid}."
    return f"Current players for appid {appid}: {response.get('player_count')}"


@app.tool(description="Get store metadata for an app (unofficial store API): price, genres, description, etc.")
async def get_app_details(
    appid: Annotated[int, Field(description="Steam appid")],
    country_code: Annotated[str, Field(description="ISO country code for pricing, e.g. 'no', 'us'")] = "no",
    language: Annotated[str, Field(description="Language for text fields")] = "norwegian",
) -> str:
    data = await _client().get_store("/api/appdetails", appids=appid, cc=country_code, l=language)
    entry = data.get(str(appid), {})
    if not entry.get("success"):
        return f"No store details found for appid {appid}."

    app_data = entry.get("data", {})
    lines = [
        f"# {app_data.get('name', '(unknown)')}",
        f"**Type:** {app_data.get('type', '?')}",
        f"**Free:** {app_data.get('is_free', False)}",
    ]
    price = app_data.get("price_overview")
    if price:
        lines.append(
            f"**Price:** {price.get('final', 0) / 100} {price.get('currency', '')} "
            f"({price.get('discount_percent', 0)}% off)"
        )
    genres = ", ".join(g.get("description", "") for g in app_data.get("genres", []))
    if genres:
        lines.append(f"**Genres:** {genres}")
    lines += ["", "## Details", "```json", json.dumps(app_data, indent=2, ensure_ascii=False), "```"]
    return "\n".join(lines)


@app.tool(description="Get review summary for an app (unofficial store API).")
async def get_app_reviews(
    appid: Annotated[int, Field(description="Steam appid")],
) -> str:
    data = await _client().get_store(f"/appreviews/{appid}", json=1, language="all", purchase_type="all")
    summary = data.get("query_summary", {})
    if not summary:
        return f"No review summary found for appid {appid}."

    return (
        f"# Reviews for appid {appid}\n"
        f"**Score:** {summary.get('review_score_desc', '?')}\n"
        f"**Positive:** {summary.get('total_positive', 0)}\n"
        f"**Negative:** {summary.get('total_negative', 0)}\n"
        f"**Total:** {summary.get('total_reviews', 0)}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-steamapi/tests/test_store_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-steamapi/src/mcp_steamapi/__main__.py packages/mcp-steamapi/tests/test_store_tools.py
git commit -m "feat(mcp-steamapi): add search_app_by_name, get_current_player_count, get_app_details, get_app_reviews tools"
```

---

### Task 11: Package README + full verification

**Files:**
- Create: `packages/mcp-steamapi/README.md`

**Interfaces:** None — documentation and final verification only.

- [ ] **Step 1: Write `packages/mcp-steamapi/README.md`**

```markdown
# mcp-steamapi

MCP server for the [Steam Web API](https://steamcommunity.com/dev): achievement mapping,
library/playtime, profile and social lookups, and store metadata.

## Requirements

- A Steam Web API key from https://steamcommunity.com/dev/apikey (requires a Steam account that
  has spent at least $5 USD), set as the `STEAM_API_KEY` environment variable. No CLI flag exists
  for the key, to avoid it ever landing in a process table or client config JSON.

## Tools

| Tool | Description |
|---|---|
| `resolve_vanity_url` | Resolve a vanity URL name to a SteamID64 |
| `get_player_summary` | Profile summary, including public visibility state (preflight check) |
| `get_owned_games` | All games a player owns, with playtime |
| `get_recently_played_games` | Games played in the last 2 weeks |
| `get_game_achievements_schema` | All achievements available for a game (cached) |
| `get_player_achievements` | A player's unlocked/locked achievements for a game |
| `get_global_achievement_percentages` | Global unlock rarity for a game's achievements |
| `get_user_stats_for_game` | Numeric stats (progression counters) |
| `get_steam_level` | A player's Steam level |
| `get_badges` | A player's badges and XP |
| `get_friend_list` | A player's friend list |
| `get_player_bans` | VAC/game/community ban status |
| `search_app_by_name` | Search the Steam catalog by name (cached) |
| `get_current_player_count` | Current in-game player count for an app |
| `get_app_details` | Store metadata: price, genres, description |
| `get_app_reviews` | Review score summary |

## Scope notes

- Achievement mapping requires a **Public** profile and **Public** "Game details" privacy
  setting (two separate Steam settings) — `get_player_summary` surfaces visibility explicitly,
  and `get_owned_games`/`get_player_achievements` give a clear message instead of a silent empty
  result when either is private.
- `get_player_summary`/`get_player_bans` accept a single SteamID64 per call — no batch lookups in
  this version.
- `get_game_achievements_schema` and `search_app_by_name` cache their (large, slow-changing)
  responses in memory for 7 days; nothing else is cached. See
  `docs/superpowers/specs/2026-08-22-mcp-steamapi-design.md` for the reasoning.
- No proxy support in this version.

## Local development

```bash
STEAM_API_KEY=your_key_here uv --directory packages/mcp-steamapi run mcp-steamapi
uv --directory packages/mcp-steamapi run pytest
```
```

- [ ] **Step 2: Run the full package test suite**

Run: `uv run pytest packages/mcp-steamapi/tests -v`
Expected: All tests across `test_normalize.py`, `test_ratelimit.py`, `test_cache.py`,
`test_client.py`, `test_cli.py`, `test_identity_library_tools.py`,
`test_achievements_join_tools.py`, `test_stats_social_tools.py`, `test_store_tools.py` PASS.

- [ ] **Step 3: Run the whole-repo test suite to confirm no regressions**

Run: `uv run pytest`
Expected: All tests in `mcp-fetch-select`, `mcp-recipe-scraper`, `mcp-openlibrary`, and
`mcp-steamapi` PASS.

- [ ] **Step 4: Smoke-test the CLI**

Run: `STEAM_API_KEY=test uv run --directory packages/mcp-steamapi mcp-steamapi --help`
Expected: Usage text lists `--transport`, `--host`, `--port`, `--path`.

Run: `uv run --directory packages/mcp-steamapi mcp-steamapi --help` (no `STEAM_API_KEY` set)
Expected: `--help` still works (argparse handles `--help` before `main()`'s body runs `_client()`).

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-steamapi/README.md
git commit -m "docs(mcp-steamapi): add package README"
```
