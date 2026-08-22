# mcp-openlibrary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `mcp-openlibrary`, a new MCP server package exposing 8 tools over the Open Library API (book search, work/edition/author lookup, subject browsing, cover URL building).

**Architecture:** New standalone package under `packages/mcp-openlibrary/`, following the existing packages' shape (argparse CLI, `MCPServer` app, `src/` layout, `uv_build`), but splitting logic across `normalize.py` (pure helpers), `ratelimit.py` (token bucket), and `client.py` (HTTP layer) rather than one file, since this package has more surface area than the existing two.

**Tech Stack:** Python 3.12+, `mcp[cli]`, `httpx` (async), `pydantic`, `pytest` + `pytest`'s `monkeypatch` for fakes (no live network calls in tests).

**Spec:** `docs/superpowers/specs/2026-08-22-mcp-openlibrary-design.md`

## Global Constraints

- Python `>=3.12`, `uv_build` backend, `src/` layout, `[project.scripts] mcp-openlibrary = "mcp_openlibrary:main"` — matches `packages/mcp-recipe-scraper/pyproject.toml` exactly in shape.
- Dependencies pinned like `mcp-recipe-scraper`: `mcp[cli]>=2.0.0,<3`, `httpx>=0.27,<0.29`, `pydantic>=2,<3`. No `recipe-scrapers`/`bs4` — this package is JSON-only.
- No proxy support, no response caching — explicitly out of scope for v1 (spec §8).
- `search.json` calls always pass an explicit `fields=` — never `fields=*`.
- `unwrap()` applied to `description`/`bio`/`first_sentence` before display.
- `-1` filtered out of every cover-ID list before display.
- Cover URLs always end in `?default=false`.
- `get_json()` retries only on `429`/`500`/`502`/`503`/`504`; a `404` or `{"error":"notfound"}` body returns `None` immediately, no retry.
- `get_cover_url` never makes an HTTP request — it's a pure URL builder.
- No test in this plan makes a live network call — every HTTP boundary is faked via `monkeypatch`.
- When staging files for commit, stage by exact filename (`git add <file> <file>`) — never `git add -A`/`git add .`.

---

### Task 1: Package scaffolding

**Files:**
- Create: `packages/mcp-openlibrary/pyproject.toml`
- Create: `packages/mcp-openlibrary/src/mcp_openlibrary/__init__.py`
- Create: `packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py`
- Modify: `pyproject.toml` (repo root)
- Modify: `README.md` (repo root)

**Interfaces:**
- Produces: `mcp_openlibrary.__main__.app` (an `MCPServer` instance), `mcp_openlibrary.__main__.main() -> None`, `mcp_openlibrary.main` (re-exported), the `mcp-openlibrary` console script, and an importable `mcp_openlibrary` package with an empty `src/mcp_openlibrary/client.py`/`ratelimit.py`/`normalize.py` yet to be created in later tasks.

- [ ] **Step 1: Create `packages/mcp-openlibrary/pyproject.toml`**

```toml
[project]
name = "mcp-openlibrary"
version = "0.1.0"
description = "MCP server for the Open Library API (search, works, editions, authors, subjects, covers)"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=2.0.0,<3",
    "httpx>=0.27,<0.29",
    "pydantic>=2,<3",
]

[project.scripts]
mcp-openlibrary = "mcp_openlibrary:main"

[build-system]
requires = ["uv_build>=0.11.13,<0.12"]
build-backend = "uv_build"

[tool.hatch.build.targets.wheel]
packages = ["src/mcp_openlibrary"]

[dependency-groups]
dev = ["pytest>=8,<9"]
```

- [ ] **Step 2: Create `packages/mcp-openlibrary/src/mcp_openlibrary/__init__.py`**

```python
from mcp_openlibrary.__main__ import main

__all__ = ["main"]
```

- [ ] **Step 3: Create `packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py`** (transport-only skeleton; CLIENT wiring and tools land in later tasks)

```python
import argparse

from mcp.server.mcpserver import MCPServer

app = MCPServer("mcp-openlibrary")


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-openlibrary")
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

In `pyproject.toml` (repo root), add `mcp-openlibrary` to `dependencies` and `[tool.uv.sources]`:

```toml
[project]
name = "mcp-tools"
version = "0.1.0"
description = "MCP server collection"
requires-python = ">=3.12"
dependencies = [
  "mcp-fetch-select", "mcp-recipe-scraper", "mcp-openlibrary",
]

[tool.uv.sources]
mcp-fetch-select = { workspace = true }
mcp-recipe-scraper = { workspace = true }
mcp-openlibrary = { workspace = true }

[tool.uv.workspace]
members = ["packages/*"]

[tool.pytest.ini_options]
addopts = "--import-mode=importlib"
```

- [ ] **Step 5: Add a row to the package table in `README.md`**

In the `## Packages` table, add:

```markdown
| [mcp-openlibrary](packages/mcp-openlibrary/) | Search books, works, editions, authors, and subjects via the Open Library API |
```

- [ ] **Step 6: Verify the package installs and runs**

Run:
```bash
uv sync
uv run --directory packages/mcp-openlibrary mcp-openlibrary --help
```
Expected: `uv sync` succeeds; `--help` prints usage including `--transport`/`--host`/`--port`/`--path`. No `tests/` directory exists yet — Task 2 creates it along with the first test file, so there's nothing to run with pytest at this point.

- [ ] **Step 7: Commit**

```bash
git add packages/mcp-openlibrary/pyproject.toml packages/mcp-openlibrary/src/mcp_openlibrary/__init__.py packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py pyproject.toml README.md
git commit -m "feat(mcp-openlibrary): scaffold new package"
```

---

### Task 2: `normalize.py` — pure data-shape helpers

**Files:**
- Create: `packages/mcp-openlibrary/src/mcp_openlibrary/normalize.py`
- Test: `packages/mcp-openlibrary/tests/test_normalize.py`

**Interfaces:**
- Produces: `unwrap(value)`, `olid_kind(olid: str) -> Literal["work","edition","author","list"] | None`, `strip_missing_covers(cover_ids: list[int]) -> list[int]`, `cover_url(id_type: str, id_value: str, size: str = "M", kind: str = "book") -> str` (raises `ValueError` on bad `size`/`kind`/`id_type`-for-`kind`), `subject_slug(subject: str) -> str`, `author_refs(authors: list[dict]) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-openlibrary/tests/test_normalize.py
import pytest

from mcp_openlibrary.normalize import (
    unwrap,
    olid_kind,
    strip_missing_covers,
    cover_url,
    subject_slug,
    author_refs,
)


def test_unwrap_passes_through_plain_string():
    assert unwrap("hello") == "hello"


def test_unwrap_extracts_value_from_wrapper():
    assert unwrap({"type": "/type/text", "value": "hello"}) == "hello"


def test_unwrap_passes_through_none():
    assert unwrap(None) is None


@pytest.mark.parametrize(
    "olid,expected",
    [
        ("OL45804W", "work"),
        ("OL7353617M", "edition"),
        ("OL23919A", "author"),
        ("OL123L", "list"),
    ],
)
def test_olid_kind_classifies_valid_olids(olid, expected):
    assert olid_kind(olid) == expected


@pytest.mark.parametrize("bad", ["", "45804W", "OL45804", "OL45804X", "works/OL45804W"])
def test_olid_kind_returns_none_for_invalid(bad):
    assert olid_kind(bad) is None


def test_strip_missing_covers_filters_negative_one():
    assert strip_missing_covers([15152634, 8739161, -1]) == [15152634, 8739161]


def test_strip_missing_covers_keeps_empty_list():
    assert strip_missing_covers([]) == []


def test_cover_url_book_by_id():
    assert (
        cover_url("id", "240727", "S", kind="book")
        == "https://covers.openlibrary.org/b/id/240727-S.jpg?default=false"
    )


def test_cover_url_book_by_isbn():
    assert (
        cover_url("isbn", "9780385472579", "M", kind="book")
        == "https://covers.openlibrary.org/b/isbn/9780385472579-M.jpg?default=false"
    )


def test_cover_url_author_by_olid():
    assert (
        cover_url("olid", "OL229501A", "L", kind="author")
        == "https://covers.openlibrary.org/a/olid/OL229501A-L.jpg?default=false"
    )


def test_cover_url_rejects_bad_size():
    with pytest.raises(ValueError):
        cover_url("id", "240727", "XL", kind="book")


def test_cover_url_rejects_bad_kind():
    with pytest.raises(ValueError):
        cover_url("id", "240727", "M", kind="magazine")


def test_cover_url_rejects_id_type_not_valid_for_kind():
    with pytest.raises(ValueError):
        cover_url("isbn", "9780385472579", "M", kind="author")


def test_subject_slug_lowercases_and_replaces_spaces():
    assert subject_slug("Science Fiction") == "science_fiction"


def test_subject_slug_strips_and_collapses_whitespace():
    assert subject_slug("  world   war  ") == "world_war"


def test_author_refs_from_work_shape():
    authors = [{"type": {"key": "/type/author_role"}, "author": {"key": "/authors/OL34184A"}}]
    assert author_refs(authors) == ["OL34184A"]


def test_author_refs_from_edition_shape():
    authors = [{"key": "/authors/OL34184A"}]
    assert author_refs(authors) == ["OL34184A"]


def test_author_refs_empty_list():
    assert author_refs([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_normalize.py -v`
Expected: FAIL/ERROR — `mcp_openlibrary.normalize` doesn't exist yet.

- [ ] **Step 3: Write `normalize.py`**

```python
# packages/mcp-openlibrary/src/mcp_openlibrary/normalize.py
import re
from typing import Literal

OlidKind = Literal["work", "edition", "author", "list"]

_OLID_RE = re.compile(r"^OL(\d+)([WMAL])$")
_KIND_BY_SUFFIX: dict[str, OlidKind] = {
    "W": "work",
    "M": "edition",
    "A": "author",
    "L": "list",
}

_BOOK_ID_TYPES = {"id", "olid", "isbn", "oclc", "lccn"}
_AUTHOR_ID_TYPES = {"id", "olid"}
_SIZES = {"S", "M", "L"}


def unwrap(value):
    """Unwrap Open Library's {"type": ..., "value": ...} scalar wrapper, if present."""
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def olid_kind(olid: str) -> OlidKind | None:
    """Classify an OLID string (e.g. "OL45804W") into its kind, or None if malformed."""
    match = _OLID_RE.match(olid)
    if not match:
        return None
    return _KIND_BY_SUFFIX[match.group(2)]


def strip_missing_covers(cover_ids: list[int]) -> list[int]:
    """Filter out the -1 sentinel Open Library uses for "no cover"."""
    return [c for c in cover_ids if c != -1]


def cover_url(id_type: str, id_value: str, size: str = "M", kind: str = "book") -> str:
    """Build a covers.openlibrary.org URL. kind is "book" or "author"."""
    if kind not in ("book", "author"):
        raise ValueError(f"kind must be 'book' or 'author', got {kind!r}")
    if size not in _SIZES:
        raise ValueError(f"size must be one of {sorted(_SIZES)}, got {size!r}")
    valid_id_types = _BOOK_ID_TYPES if kind == "book" else _AUTHOR_ID_TYPES
    if id_type not in valid_id_types:
        raise ValueError(f"id_type for kind={kind!r} must be one of {sorted(valid_id_types)}, got {id_type!r}")
    prefix = "b" if kind == "book" else "a"
    return f"https://covers.openlibrary.org/{prefix}/{id_type}/{id_value}-{size}.jpg?default=false"


def subject_slug(subject: str) -> str:
    """Normalize free-text subject input into Open Library's slug form."""
    return re.sub(r"\s+", "_", subject.strip().lower())


def author_refs(authors: list[dict]) -> list[str]:
    """Normalize a Work-shape or Edition-shape authors list into a flat list of author OLIDs.

    Work shape:    [{"author": {"key": "/authors/OL..A"}, "type": {...}}, ...]
    Edition shape: [{"key": "/authors/OL..A"}, ...]
    """
    refs = []
    for entry in authors:
        key = entry.get("author", {}).get("key") if "author" in entry else entry.get("key")
        if key:
            refs.append(key.rsplit("/", 1)[-1])
    return refs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_normalize.py -v`
Expected: PASS (all tests green).

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-openlibrary/src/mcp_openlibrary/normalize.py packages/mcp-openlibrary/tests/test_normalize.py
git commit -m "feat(mcp-openlibrary): add normalize helpers"
```

---

### Task 3: `ratelimit.py` — token bucket

**Files:**
- Create: `packages/mcp-openlibrary/src/mcp_openlibrary/ratelimit.py`
- Test: `packages/mcp-openlibrary/tests/test_ratelimit.py`

**Interfaces:**
- Produces: `TokenBucket(rate_per_sec: float)` with `.acquire() -> None` (blocks via `time.sleep` until the next slot is available).

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-openlibrary/tests/test_ratelimit.py
import mcp_openlibrary.ratelimit as ratelimit_mod
from mcp_openlibrary.ratelimit import TokenBucket


def test_first_acquire_does_not_sleep(monkeypatch):
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: 100.0)
    sleeps = []
    monkeypatch.setattr(ratelimit_mod.time, "sleep", lambda s: sleeps.append(s))

    bucket = TokenBucket(rate_per_sec=2.0)
    bucket.acquire()

    assert sleeps == []


def test_second_acquire_sleeps_for_interval(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: clock["t"])
    sleeps = []
    monkeypatch.setattr(ratelimit_mod.time, "sleep", lambda s: sleeps.append(s))

    bucket = TokenBucket(rate_per_sec=2.0)  # 0.5s interval
    bucket.acquire()
    bucket.acquire()

    assert sleeps == [0.5]


def test_acquire_does_not_sleep_if_enough_time_passed(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: clock["t"])
    sleeps = []
    monkeypatch.setattr(ratelimit_mod.time, "sleep", lambda s: sleeps.append(s))

    bucket = TokenBucket(rate_per_sec=2.0)
    bucket.acquire()
    clock["t"] = 105.0
    bucket.acquire()

    assert sleeps == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_ratelimit.py -v`
Expected: FAIL/ERROR — `mcp_openlibrary.ratelimit` doesn't exist yet.

- [ ] **Step 3: Write `ratelimit.py`**

```python
# packages/mcp-openlibrary/src/mcp_openlibrary/ratelimit.py
import threading
import time


class TokenBucket:
    """Simple rate limiter: acquire() blocks until the next slot is available."""

    def __init__(self, rate_per_sec: float):
        self._interval = 1.0 / rate_per_sec
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._interval
        if wait:
            time.sleep(wait)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_ratelimit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-openlibrary/src/mcp_openlibrary/ratelimit.py packages/mcp-openlibrary/tests/test_ratelimit.py
git commit -m "feat(mcp-openlibrary): add TokenBucket rate limiter"
```

---

### Task 4: `client.py` — HTTP layer

**Files:**
- Create: `packages/mcp-openlibrary/src/mcp_openlibrary/client.py`
- Test: `packages/mcp-openlibrary/tests/test_client.py`

**Interfaces:**
- Consumes: `TokenBucket` from `mcp_openlibrary.ratelimit` (Task 3).
- Produces: `OpenLibraryClient(user_agent: str, rate_per_sec: float = 3.0)` with `async get_json(path: str, **params) -> dict | list | None` and `async aclose() -> None`; module constants `BASE_URL`, `DEFAULT_TIMEOUT`, `RETRY_STATUS_CODES`, `MAX_ATTEMPTS`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-openlibrary/tests/test_client.py
import asyncio

import httpx
import pytest

import mcp_openlibrary.client as client_mod
import mcp_openlibrary.ratelimit as ratelimit_mod
from mcp_openlibrary.client import OpenLibraryClient


class _FakeResponse:
    def __init__(self, status_code, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.request = httpx.Request("GET", "https://openlibrary.org/x")

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=self.request, response=self)


class _FakeAsyncClient:
    def __init__(self, get_impl):
        self._get_impl = get_impl
        self.calls = []
        self.headers = None

    async def get(self, path, params=None):
        self.calls.append((path, params))
        return await self._get_impl(path, params)


def _make_client(monkeypatch, get_impl, rate_per_sec=1000.0):
    fake = _FakeAsyncClient(get_impl)

    def fake_async_client(**kw):
        fake.headers = kw.get("headers")
        return fake

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)
    monkeypatch.setattr(ratelimit_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)
    return OpenLibraryClient(user_agent="test-agent", rate_per_sec=rate_per_sec), fake


def test_get_json_returns_data_on_200(monkeypatch):
    async def get_impl(path, params):
        return _FakeResponse(200, {"key": "value"})

    client, fake = _make_client(monkeypatch, get_impl)

    result = asyncio.run(client.get_json("/works/OL45804W.json"))

    assert result == {"key": "value"}


def test_get_json_returns_none_on_404(monkeypatch):
    async def get_impl(path, params):
        return _FakeResponse(404)

    client, fake = _make_client(monkeypatch, get_impl)

    result = asyncio.run(client.get_json("/works/OLnope.json"))

    assert result is None


def test_get_json_returns_none_on_notfound_body(monkeypatch):
    async def get_impl(path, params):
        return _FakeResponse(200, {"error": "notfound", "key": "/works/OLnope"})

    client, fake = _make_client(monkeypatch, get_impl)

    result = asyncio.run(client.get_json("/works/OLnope.json"))

    assert result is None


def test_get_json_retries_on_503_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get_impl(path, params):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResponse(503)
        return _FakeResponse(200, {"ok": True})

    client, fake = _make_client(monkeypatch, get_impl)

    result = asyncio.run(client.get_json("/search.json"))

    assert result == {"ok": True}
    assert calls["n"] == 3


def test_get_json_does_not_retry_on_404(monkeypatch):
    calls = {"n": 0}

    async def get_impl(path, params):
        calls["n"] += 1
        return _FakeResponse(404)

    client, fake = _make_client(monkeypatch, get_impl)

    asyncio.run(client.get_json("/works/OLnope.json"))

    assert calls["n"] == 1


def test_get_json_raises_after_max_attempts(monkeypatch):
    async def get_impl(path, params):
        return _FakeResponse(503)

    client, fake = _make_client(monkeypatch, get_impl)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.get_json("/search.json"))


def test_get_json_passes_user_agent_header(monkeypatch):
    async def get_impl(path, params):
        return _FakeResponse(200, {})

    client, fake = _make_client(monkeypatch, get_impl)

    assert fake.headers["User-Agent"] == "test-agent"


def test_get_json_omits_none_params(monkeypatch):
    async def get_impl(path, params):
        return _FakeResponse(200, {})

    client, fake = _make_client(monkeypatch, get_impl)

    asyncio.run(client.get_json("/search.json", q="tolkien", limit=None))

    assert fake.calls[0] == ("/search.json", {"q": "tolkien"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_client.py -v`
Expected: FAIL/ERROR — `mcp_openlibrary.client` doesn't exist yet.

- [ ] **Step 3: Write `client.py`**

```python
# packages/mcp-openlibrary/src/mcp_openlibrary/client.py
import time

import httpx

from mcp_openlibrary.ratelimit import TokenBucket

BASE_URL = "https://openlibrary.org"
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5


class OpenLibraryClient:
    def __init__(self, user_agent: str, rate_per_sec: float = 3.0):
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
        self._bucket = TokenBucket(rate_per_sec)

    async def get_json(self, path: str, **params) -> dict | list | None:
        """GET path (relative to BASE_URL). Returns None on 404 or a {"error": "notfound"} body."""
        query = {k: v for k, v in params.items() if v is not None}
        for attempt in range(MAX_ATTEMPTS):
            self._bucket.acquire()
            response = await self._http.get(path, params=query or None)
            if response.status_code in RETRY_STATUS_CODES:
                if attempt == MAX_ATTEMPTS - 1:
                    response.raise_for_status()
                time.sleep(2**attempt)
                continue
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("error") == "notfound":
                return None
            return data
        raise RuntimeError(f"gave up after {MAX_ATTEMPTS} attempts: {path}")

    async def aclose(self) -> None:
        await self._http.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-openlibrary/src/mcp_openlibrary/client.py packages/mcp-openlibrary/tests/test_client.py
git commit -m "feat(mcp-openlibrary): add OpenLibraryClient HTTP layer"
```

---

### Task 5: CLI user-agent flag + `CLIENT` global wiring

**Files:**
- Modify: `packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py`
- Test: `packages/mcp-openlibrary/tests/test_cli.py`

**Interfaces:**
- Consumes: `OpenLibraryClient` from `mcp_openlibrary.client` (Task 4).
- Produces: `DEFAULT_USER_AGENT: str`, `_resolve_user_agent(cli_value: str | None) -> str`, module global `CLIENT: OpenLibraryClient | None` (set inside `main()`), `--user-agent` CLI flag / `OPENLIBRARY_USER_AGENT` env var.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-openlibrary/tests/test_cli.py
from mcp_openlibrary.__main__ import _resolve_user_agent, DEFAULT_USER_AGENT


def test_resolve_user_agent_cli_wins(monkeypatch):
    monkeypatch.setenv("OPENLIBRARY_USER_AGENT", "env-agent")
    assert _resolve_user_agent("cli-agent") == "cli-agent"


def test_resolve_user_agent_env_wins_when_cli_none(monkeypatch):
    monkeypatch.setenv("OPENLIBRARY_USER_AGENT", "env-agent")
    assert _resolve_user_agent(None) == "env-agent"


def test_resolve_user_agent_default_when_neither_set(monkeypatch):
    monkeypatch.delenv("OPENLIBRARY_USER_AGENT", raising=False)
    assert _resolve_user_agent(None) == DEFAULT_USER_AGENT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_cli.py -v`
Expected: FAIL — `_resolve_user_agent`/`DEFAULT_USER_AGENT` don't exist yet.

- [ ] **Step 3: Update `__main__.py`**

Replace the full file with:

```python
# packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py
import argparse
import os

from mcp.server.mcpserver import MCPServer

from mcp_openlibrary.client import OpenLibraryClient

app = MCPServer("mcp-openlibrary")

DEFAULT_USER_AGENT = "mcp-openlibrary/0.1.0 (+https://github.com/bjafl/mcp-tools)"

CLIENT: OpenLibraryClient | None = None


def _resolve_user_agent(cli_value: str | None) -> str:
    """CLI value wins; else OPENLIBRARY_USER_AGENT env var; else the default."""
    if cli_value is not None:
        return cli_value
    return os.environ.get("OPENLIBRARY_USER_AGENT", DEFAULT_USER_AGENT)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-openlibrary")
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
        "--user-agent",
        default=None,
        help="User-Agent header for Open Library requests (overrides OPENLIBRARY_USER_AGENT)",
    )
    args = parser.parse_args()

    global CLIENT
    CLIENT = OpenLibraryClient(user_agent=_resolve_user_agent(args.user_agent))

    if args.transport == "streamable-http":
        app.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        app.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py packages/mcp-openlibrary/tests/test_cli.py
git commit -m "feat(mcp-openlibrary): wire OpenLibraryClient and --user-agent into CLI"
```

---

### Task 6: Book tools — `search_books`, `get_work`, `get_edition`, `get_cover_url`

**Files:**
- Modify: `packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py`
- Test: `packages/mcp-openlibrary/tests/test_book_tools.py`

**Interfaces:**
- Consumes: `CLIENT` global and `_resolve_user_agent`/`app` from Task 5; `unwrap`, `olid_kind`, `strip_missing_covers`, `cover_url`, `author_refs` from `mcp_openlibrary.normalize` (Task 2).
- Produces: `_not_found(kind: str, identifier: str) -> str`, `_is_isbn(identifier: str) -> bool`, `DEFAULT_SEARCH_FIELDS: str`, and tool functions `search_books`, `get_work`, `get_edition`, `get_cover_url` — all consumed directly by tests via `main_mod.<tool_name>(...)`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-openlibrary/tests/test_book_tools.py
import asyncio

import mcp_openlibrary.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get_json(self, path, **params):
        self.calls.append((path, params))
        return self.response


def test_search_books_formats_results(monkeypatch):
    fake = _FakeClient({
        "numFound": 2,
        "docs": [
            {"key": "/works/OL1W", "title": "The Hobbit", "author_name": ["J.R.R. Tolkien"], "first_publish_year": 1937},
        ],
    })
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_books(query="hobbit"))

    assert "The Hobbit" in result
    assert "J.R.R. Tolkien" in result
    assert "OL1W" in result
    assert fake.calls[0][1]["q"] == "hobbit"


def test_search_books_no_results(monkeypatch):
    fake = _FakeClient({"numFound": 0, "docs": []})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_books(query="zzzznoexist"))

    assert "No books found" in result


def test_search_books_caps_limit_at_100(monkeypatch):
    fake = _FakeClient({"numFound": 0, "docs": []})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    asyncio.run(main_mod.search_books(query="x", limit=500))

    assert fake.calls[0][1]["limit"] == 100


def test_get_work_returns_summary(monkeypatch):
    fake = _FakeClient({
        "key": "/works/OL45804W",
        "title": "Fantastic Mr. Fox",
        "description": "A fox story.",
        "authors": [{"type": {"key": "/type/author_role"}, "author": {"key": "/authors/OL34184A"}}],
        "subjects": ["Foxes"],
        "covers": [8739161, -1],
    })
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_work(olid="OL45804W"))

    assert "Fantastic Mr. Fox" in result
    assert "OL34184A" in result
    assert "8739161" in result
    assert "-1" not in result


def test_get_work_rejects_invalid_olid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_work(olid="not-an-olid"))

    assert "not a valid work OLID" in result
    assert fake.calls == []


def test_get_work_not_found(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_work(olid="OL999999999W"))

    assert "No work found" in result


def test_get_edition_by_olid(monkeypatch):
    fake = _FakeClient({
        "key": "/books/OL7353617M",
        "title": "Fantastic Mr. Fox",
        "authors": [{"key": "/authors/OL34184A"}],
        "isbn_10": ["014032871X"],
    })
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_edition(identifier="OL7353617M"))

    assert "Fantastic Mr. Fox" in result
    assert fake.calls[0][0] == "/books/OL7353617M.json"


def test_get_edition_by_isbn(monkeypatch):
    fake = _FakeClient({"key": "/books/OL7353617M", "title": "Fantastic Mr. Fox"})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    asyncio.run(main_mod.get_edition(identifier="9780140328721"))

    assert fake.calls[0][0] == "/isbn/9780140328721.json"


def test_get_edition_rejects_garbage_identifier(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_edition(identifier="not-valid"))

    assert "not a valid edition OLID or ISBN" in result
    assert fake.calls == []


def test_get_cover_url_makes_no_http_call(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_cover_url(id_type="id", id_value="240727", size="S", kind="book"))

    assert result == "https://covers.openlibrary.org/b/id/240727-S.jpg?default=false"
    assert fake.calls == []


def test_get_cover_url_rejects_bad_size(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_cover_url(id_type="id", id_value="240727", size="XL", kind="book"))

    assert "must be" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_book_tools.py -v`
Expected: FAIL — `search_books`/`get_work`/`get_edition`/`get_cover_url` don't exist yet.

- [ ] **Step 3: Add imports and tool functions to `__main__.py`**

Add these imports near the top (alongside the existing ones from Task 5):

```python
import json
import re
from typing import Annotated

from pydantic import Field

from mcp_openlibrary.normalize import author_refs, cover_url, olid_kind, strip_missing_covers, unwrap
```

Add these module-level constants and helper, placed after `CLIENT: OpenLibraryClient | None = None`:

```python
DEFAULT_SEARCH_FIELDS = (
    "key,title,subtitle,author_key,author_name,first_publish_year,"
    "publish_year,publisher,language,edition_count,edition_key,isbn,"
    "cover_i,cover_edition_key,subject,ebook_access,has_fulltext,ia,"
    "ratings_average,ratings_count,number_of_pages_median,lcc,ddc"
)

_ISBN_RE = re.compile(r"^[0-9Xx-]{10,17}$")


def _not_found(kind: str, identifier: str) -> str:
    return f"No {kind} found for '{identifier}'."


def _is_isbn(identifier: str) -> bool:
    digits = identifier.replace("-", "")
    return bool(_ISBN_RE.match(identifier)) and len(digits) in (10, 13)
```

Add the four tool functions, placed after `main()` is fine but before the `if __name__ == "__main__":` guard — order in the file doesn't matter for `@app.tool`, keep them grouped together above `main()`:

```python
@app.tool(description="Search Open Library for books by title, author, subject, or a Solr query.")
async def search_books(
    query: Annotated[str, Field(description="Search query, e.g. 'tolkien' or 'title:hobbit AND author_name:tolkien'")],
    fields: Annotated[
        str | None,
        Field(description="Comma-separated fields to return. Defaults to a curated set; avoid '*' (expensive)."),
    ] = None,
    sort: Annotated[str | None, Field(description="Sort order, e.g. 'rating desc', 'new'. Default: relevance")] = None,
    limit: Annotated[int, Field(description="Results per page, max 100")] = 10,
    page: Annotated[int, Field(description="1-indexed page number")] = 1,
) -> str:
    limit = min(limit, 100)
    data = await CLIENT.get_json(
        "/search.json",
        q=query,
        fields=fields or DEFAULT_SEARCH_FIELDS,
        sort=sort,
        limit=limit,
        page=page,
    )
    docs = (data or {}).get("docs", [])
    if not docs:
        return f"No books found for query '{query}'."

    total = data.get("numFound", len(docs))
    lines = [f"# {total} result(s) for '{query}' (showing {len(docs)}, page {page})"]
    for doc in docs:
        title = doc.get("title", "(untitled)")
        authors = ", ".join(doc.get("author_name", []) or []) or "unknown author"
        year = doc.get("first_publish_year", "?")
        key = doc.get("key", "")
        lines.append(f"- **{title}** by {authors} ({year}) — `{key}`")
    return "\n".join(lines)


@app.tool(description="Get details for a single Open Library work by its OLID (e.g. 'OL45804W').")
async def get_work(
    olid: Annotated[str, Field(description="Work OLID, e.g. 'OL45804W'")],
) -> str:
    if olid_kind(olid) != "work":
        return f"'{olid}' is not a valid work OLID (expected a pattern like 'OL45804W')."

    data = await CLIENT.get_json(f"/works/{olid}.json")
    if data is None:
        return _not_found("work", olid)

    summary = {
        "olid": olid,
        "title": data.get("title"),
        "description": unwrap(data.get("description")),
        "authors": author_refs(data.get("authors", [])),
        "subjects": data.get("subjects", []),
        "subject_people": data.get("subject_people", []),
        "subject_places": data.get("subject_places", []),
        "subject_times": data.get("subject_times", []),
        "covers": strip_missing_covers(data.get("covers", [])),
    }
    lines = [f"# {summary['title'] or '(untitled)'}", f"**OLID:** {olid}"]
    if summary["authors"]:
        lines.append(f"**Authors:** {', '.join(summary['authors'])}")
    if summary["description"]:
        lines += ["", summary["description"]]
    lines += ["", "## Details", "```json", json.dumps(summary, indent=2, ensure_ascii=False), "```"]
    return "\n".join(lines)


@app.tool(description="Get details for a book edition by its OLID (e.g. 'OL7353617M') or ISBN-10/13.")
async def get_edition(
    identifier: Annotated[str, Field(description="Edition OLID (e.g. 'OL7353617M') or ISBN-10/13")],
) -> str:
    kind = olid_kind(identifier)
    if kind == "edition":
        path = f"/books/{identifier}.json"
    elif kind is None and _is_isbn(identifier):
        path = f"/isbn/{identifier}.json"
    else:
        return f"'{identifier}' is not a valid edition OLID or ISBN."

    data = await CLIENT.get_json(path)
    if data is None:
        return _not_found("edition", identifier)

    summary = {
        "key": data.get("key"),
        "title": data.get("title"),
        "authors": author_refs(data.get("authors", [])),
        "isbn_10": data.get("isbn_10", []),
        "isbn_13": data.get("isbn_13", []),
        "publishers": data.get("publishers", []),
        "publish_date": data.get("publish_date"),
        "number_of_pages": data.get("number_of_pages"),
        "languages": [lang.get("key", "").rsplit("/", 1)[-1] for lang in data.get("languages", [])],
        "first_sentence": unwrap(data.get("first_sentence")),
        "covers": strip_missing_covers(data.get("covers", [])),
        "works": [w.get("key") for w in data.get("works", [])],
    }
    lines = [f"# {summary['title'] or '(untitled)'}", f"**Key:** {summary['key']}"]
    if summary["authors"]:
        lines.append(f"**Authors:** {', '.join(summary['authors'])}")
    if summary["publish_date"]:
        lines.append(f"**Published:** {summary['publish_date']}")
    lines += ["", "## Details", "```json", json.dumps(summary, indent=2, ensure_ascii=False), "```"]
    return "\n".join(lines)


@app.tool(
    description=(
        "Build a cover image URL from a cover ID/OLID/ISBN/OCLC/LCCN identifier. "
        "Makes no network request."
    )
)
async def get_cover_url(
    id_type: Annotated[str, Field(description="One of: id, olid, isbn, oclc, lccn (book) or id, olid (author)")],
    id_value: Annotated[str, Field(description="The identifier value, e.g. a cover ID, OLID, or ISBN")],
    size: Annotated[str, Field(description="S, M, or L")] = "M",
    kind: Annotated[str, Field(description="'book' or 'author'")] = "book",
) -> str:
    try:
        return cover_url(id_type, id_value, size, kind=kind)
    except ValueError as exc:
        return str(exc)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_book_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py packages/mcp-openlibrary/tests/test_book_tools.py
git commit -m "feat(mcp-openlibrary): add search_books, get_work, get_edition, get_cover_url tools"
```

---

### Task 7: Author & subject tools — `search_authors`, `get_author`, `get_author_works`, `search_subjects`

**Files:**
- Modify: `packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py`
- Test: `packages/mcp-openlibrary/tests/test_author_subject_tools.py`

**Interfaces:**
- Consumes: `CLIENT`, `app`, `_not_found` from Task 6; `unwrap`, `olid_kind`, `strip_missing_covers`, `subject_slug` from `mcp_openlibrary.normalize` (Task 2).
- Produces: tool functions `search_authors`, `get_author`, `get_author_works`, `search_subjects`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/mcp-openlibrary/tests/test_author_subject_tools.py
import asyncio

import mcp_openlibrary.__main__ as main_mod


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get_json(self, path, **params):
        self.calls.append((path, params))
        return self.response


def test_search_authors_formats_results(monkeypatch):
    fake = _FakeClient({"numFound": 1, "docs": [{"key": "OL23919A", "name": "J. K. Rowling", "work_count": 55}]})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_authors(query="rowling"))

    assert "J. K. Rowling" in result
    assert "OL23919A" in result


def test_search_authors_no_results(monkeypatch):
    fake = _FakeClient({"numFound": 0, "docs": []})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_authors(query="zzzznoexist"))

    assert "No authors found" in result


def test_get_author_returns_summary(monkeypatch):
    fake = _FakeClient({
        "key": "/authors/OL23919A",
        "name": "J. K. Rowling",
        "bio": {"type": "/type/text", "value": "British author."},
        "birth_date": "31 July 1965",
        "photos": [12345, -1],
    })
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author(olid="OL23919A"))

    assert "J. K. Rowling" in result
    assert "British author." in result
    assert "12345" in result
    assert "-1" not in result


def test_get_author_rejects_invalid_olid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author(olid="OL123W"))

    assert "not a valid author OLID" in result
    assert fake.calls == []


def test_get_author_not_found(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author(olid="OL999999999A"))

    assert "No author found" in result


def test_get_author_works_lists_entries_and_pagination(monkeypatch):
    fake = _FakeClient({
        "size": 418,
        "links": {"next": "/authors/OL23919A/works.json?limit=1&offset=1"},
        "entries": [{"key": "/works/OL45860018W", "title": "Harry Potter"}],
    })
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author_works(olid="OL23919A", limit=1, offset=0))

    assert "Harry Potter" in result
    assert "418" in result
    assert "More results available" in result
    assert "offset=1" in result


def test_get_author_works_no_more_when_next_missing(monkeypatch):
    fake = _FakeClient({"size": 1, "links": {}, "entries": [{"key": "/works/OL1W", "title": "Only Book"}]})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author_works(olid="OL23919A"))

    assert "More results available" not in result


def test_get_author_works_rejects_invalid_olid(monkeypatch):
    fake = _FakeClient(None)
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.get_author_works(olid="not-an-olid"))

    assert "not a valid author OLID" in result
    assert fake.calls == []


def test_search_subjects_slugifies_and_lists_works(monkeypatch):
    fake = _FakeClient({"work_count": 18969, "works": [{"key": "/works/OL262759W", "title": "Wuthering Heights"}]})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_subjects(subject="Science Fiction"))

    assert "Wuthering Heights" in result
    assert fake.calls[0][0] == "/subjects/science_fiction.json"


def test_search_subjects_passes_details_flag(monkeypatch):
    fake = _FakeClient({"work_count": 1, "works": [{"key": "/works/OL1W", "title": "X"}]})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    asyncio.run(main_mod.search_subjects(subject="love", details=True))

    assert fake.calls[0][1]["details"] == "true"


def test_search_subjects_no_results(monkeypatch):
    fake = _FakeClient({"work_count": 0, "works": []})
    monkeypatch.setattr(main_mod, "CLIENT", fake)

    result = asyncio.run(main_mod.search_subjects(subject="nonexistent"))

    assert "No works found" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_author_subject_tools.py -v`
Expected: FAIL — `search_authors`/`get_author`/`get_author_works`/`search_subjects` don't exist yet.

- [ ] **Step 3: Add the four tool functions to `__main__.py`**

Add this import alongside the existing `mcp_openlibrary.normalize` import from Task 6 (extend the existing `from mcp_openlibrary.normalize import ...` line to include `subject_slug`):

```python
from mcp_openlibrary.normalize import author_refs, cover_url, olid_kind, strip_missing_covers, subject_slug, unwrap
```

Add the four tool functions, grouped with the others above `main()`:

```python
@app.tool(description="Search Open Library for authors by name.")
async def search_authors(
    query: Annotated[str, Field(description="Author name or query")],
    limit: Annotated[int, Field(description="Results to return, max 100")] = 10,
) -> str:
    limit = min(limit, 100)
    data = await CLIENT.get_json("/search/authors.json", q=query, limit=limit)
    docs = (data or {}).get("docs", [])
    if not docs:
        return f"No authors found for query '{query}'."

    total = data.get("numFound", len(docs))
    lines = [f"# {total} author(s) for '{query}' (showing {len(docs)})"]
    for doc in docs:
        name = doc.get("name", "(unnamed)")
        key = doc.get("key", "")
        work_count = doc.get("work_count", "?")
        lines.append(f"- **{name}** — {work_count} work(s) — `{key}`")
    return "\n".join(lines)


@app.tool(description="Get details for a single Open Library author by OLID (e.g. 'OL23919A').")
async def get_author(
    olid: Annotated[str, Field(description="Author OLID, e.g. 'OL23919A'")],
) -> str:
    if olid_kind(olid) != "author":
        return f"'{olid}' is not a valid author OLID (expected a pattern like 'OL23919A')."

    data = await CLIENT.get_json(f"/authors/{olid}.json")
    if data is None:
        return _not_found("author", olid)

    summary = {
        "olid": olid,
        "name": data.get("name"),
        "alternate_names": data.get("alternate_names", []),
        "bio": unwrap(data.get("bio")),
        "birth_date": data.get("birth_date"),
        "death_date": data.get("death_date"),
        "remote_ids": data.get("remote_ids", {}),
        "photos": strip_missing_covers(data.get("photos", [])),
    }
    lines = [f"# {summary['name'] or '(unnamed)'}", f"**OLID:** {olid}"]
    if summary["birth_date"]:
        lines.append(f"**Born:** {summary['birth_date']}")
    if summary["bio"]:
        lines += ["", summary["bio"]]
    lines += ["", "## Details", "```json", json.dumps(summary, indent=2, ensure_ascii=False), "```"]
    return "\n".join(lines)


@app.tool(description="List works by an author, paginated.")
async def get_author_works(
    olid: Annotated[str, Field(description="Author OLID, e.g. 'OL23919A'")],
    limit: Annotated[int, Field(description="Results per page, max 100")] = 50,
    offset: Annotated[int, Field(description="Pagination offset")] = 0,
) -> str:
    if olid_kind(olid) != "author":
        return f"'{olid}' is not a valid author OLID (expected a pattern like 'OL23919A')."

    limit = min(limit, 100)
    data = await CLIENT.get_json(f"/authors/{olid}/works.json", limit=limit, offset=offset)
    if data is None:
        return _not_found("author", olid)

    entries = data.get("entries", [])
    if not entries:
        return f"No works found for author '{olid}'."

    total = data.get("size", len(entries))
    has_more = bool(data.get("links", {}).get("next"))
    lines = [f"# {total} work(s) by {olid} (showing {len(entries)} from offset {offset})"]
    for entry in entries:
        title = entry.get("title", "(untitled)")
        key = entry.get("key", "")
        lines.append(f"- **{title}** — `{key}`")
    if has_more:
        lines.append(f"\n_More results available — call again with offset={offset + limit}._")
    return "\n".join(lines)


@app.tool(description="Search/browse Open Library by subject, e.g. 'science fiction' or 'love'.")
async def search_subjects(
    subject: Annotated[str, Field(description="Subject name, e.g. 'science fiction' (auto-slugified)")],
    details: Annotated[bool, Field(description="Include extra facet data (authors, publishers, publishing_history)")] = False,
    limit: Annotated[int, Field(description="Works to return, max 100")] = 10,
    offset: Annotated[int, Field(description="Pagination offset")] = 0,
) -> str:
    limit = min(limit, 100)
    slug = subject_slug(subject)
    data = await CLIENT.get_json(
        f"/subjects/{slug}.json",
        details="true" if details else None,
        limit=limit,
        offset=offset,
    )
    if data is None:
        return _not_found("subject", slug)

    works = data.get("works", [])
    if not works:
        return f"No works found for subject '{slug}'."

    total = data.get("work_count", len(works))
    lines = [f"# {total} work(s) for subject '{slug}' (showing {len(works)} from offset {offset})"]
    for work in works:
        title = work.get("title", "(untitled)")
        key = work.get("key", "")
        lines.append(f"- **{title}** — `{key}`")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mcp-openlibrary/tests/test_author_subject_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-openlibrary/src/mcp_openlibrary/__main__.py packages/mcp-openlibrary/tests/test_author_subject_tools.py
git commit -m "feat(mcp-openlibrary): add search_authors, get_author, get_author_works, search_subjects tools"
```

---

### Task 8: Package README + full verification

**Files:**
- Create: `packages/mcp-openlibrary/README.md`

**Interfaces:** None — documentation and final verification only.

- [ ] **Step 1: Write `packages/mcp-openlibrary/README.md`**

```markdown
# mcp-openlibrary

MCP server for the [Open Library](https://openlibrary.org/developers/api) API: search books,
look up works/editions/authors, browse by subject, and build cover image URLs.

No API key required — all endpoints are open and unauthenticated.

## Tools

| Tool | Description |
|---|---|
| `search_books` | Search books by title/author/subject/Solr query |
| `get_work` | Get a work's details by OLID (e.g. `OL45804W`) |
| `get_edition` | Get an edition's details by OLID (e.g. `OL7353617M`) or ISBN-10/13 |
| `search_authors` | Search authors by name |
| `get_author` | Get an author's details by OLID (e.g. `OL23919A`) |
| `get_author_works` | List works by an author, paginated |
| `search_subjects` | Browse works by subject, e.g. "science fiction" |
| `get_cover_url` | Build a cover image URL — no network request |

## Scope notes

- `get_work`/`get_edition` return author references as OLIDs, not resolved names — call
  `get_author` if you need the name.
- No proxy support and no response caching in this version; see
  `docs/superpowers/specs/2026-08-22-mcp-openlibrary-design.md` for the reasoning.
- `--user-agent` / `OPENLIBRARY_USER_AGENT` let you set a custom User-Agent (e.g. to add contact
  info for Open Library's higher rate tier); the default identifies the tool without any personal
  contact info.

## Local development

```bash
uv --directory packages/mcp-openlibrary run mcp-openlibrary
uv --directory packages/mcp-openlibrary run pytest
```
```

- [ ] **Step 2: Run the full package test suite**

Run: `uv run pytest packages/mcp-openlibrary/tests -v`
Expected: All tests across `test_normalize.py`, `test_ratelimit.py`, `test_client.py`, `test_cli.py`, `test_book_tools.py`, `test_author_subject_tools.py` PASS.

- [ ] **Step 3: Run the whole-repo test suite to confirm no regressions**

Run: `uv run pytest`
Expected: All tests in `mcp-fetch-select`, `mcp-recipe-scraper`, and `mcp-openlibrary` PASS.

- [ ] **Step 4: Smoke-test the CLI**

Run: `uv run --directory packages/mcp-openlibrary mcp-openlibrary --help`
Expected: Usage text lists `--transport`, `--host`, `--port`, `--path`, `--user-agent`.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp-openlibrary/README.md
git commit -m "docs(mcp-openlibrary): add package README"
```
