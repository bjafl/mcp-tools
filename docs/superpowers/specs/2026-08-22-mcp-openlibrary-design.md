# mcp-openlibrary — new MCP server package

**Status:** Approved
**Date:** 2026-08-22

## Summary

A new package, `mcp-openlibrary`, exposing Open Library's public API as 8 MCP tools: book
search, work/edition detail lookup, author search/detail/works, subject browsing, and cover
image URL building. Based on `handoff-openlibrary.md` in the repo root, which documents the API
(verified live 2026-08-22) including its data model, gotchas, and a recommended client
architecture.

Unlike `mcp-fetch-select`/`mcp-recipe-scraper` (single-file `__main__.py`), this package splits
logic across a few modules — it has substantially more surface area (8 tools, per-field
normalization quirks, pagination across three different envelope shapes) that would make one
file unwieldy. No proxy support, no response caching — scoped out for v1 (see "Explicitly out of
scope").

## 1. Package layout

```
packages/mcp-openlibrary/
  pyproject.toml
  src/mcp_openlibrary/
    __init__.py       # from mcp_openlibrary.__main__ import main
    __main__.py        # argparse CLI, MCPServer app, tool registration, app.run()
    client.py          # OpenLibraryClient: httpx session, TokenBucket, get_json()
    ratelimit.py        # TokenBucket
    normalize.py         # unwrap(), olid_kind(), cover_url(), subject_slug(), pure helpers
  tests/
    test_normalize.py
    test_ratelimit.py
    test_client.py
    test_tools.py
```

`pyproject.toml` follows the existing packages' shape exactly (`uv_build` backend,
`requires-python = ">=3.12"`, `[project.scripts] mcp-openlibrary = "mcp_openlibrary:main"`).
Dependencies: `mcp[cli]>=2.0.0,<3`, `httpx>=0.27,<0.29`, `pydantic>=2,<3` (same pins as
`mcp-recipe-scraper`). No `recipe-scrapers`/`bs4` — this package only talks JSON.

Root `pyproject.toml` and `README.md` get the new package added, per the existing "Adding a new
package" checklist (workspace `dependencies`/`tool.uv.sources`, README package table row).

## 2. HTTP layer (`ratelimit.py`, `client.py`)

### `TokenBucket`

Straight port of the handoff's `TokenBucket` (§9): `acquire()` blocks until the next slot is
available, based on `rate_per_sec`. Thread-safe via a `Lock` (kept from the handoff even though
this package is asyncio-single-threaded, since `mcp[cli]` may dispatch tool calls from a thread
pool depending on transport).

### `OpenLibraryClient`

```python
BASE = "https://openlibrary.org"

class OpenLibraryClient:
    def __init__(self, user_agent: str, rate: float = 3.0):
        self._http = httpx.AsyncClient(
            base_url=BASE,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,   # required for /isbn/... and /authors/{OLID} redirects
        )
        self._bucket = TokenBucket(rate)

    async def get_json(self, path: str, **params) -> dict | list | None:
        """GET path relative to BASE. Returns None on 404 or {"error":"notfound"} body.
        Retries with exponential backoff on 429/5xx only. Raises on other failures."""
```

Only one bucket exists — for `openlibrary.org`. The handoff's second bucket (for
`covers.openlibrary.org` via ISBN/OCLC/LCCN) is not needed: `get_cover_url` never makes an HTTP
request (see §4.8), so there's no cover-domain traffic to rate-limit in this tool set.

Retry policy, ported from the handoff's client skeleton: up to 5 attempts, `2**attempt` second
backoff, only on `429`/`500`/`502`/`503`/`504`. A `404` response, or a `200` with
`{"error": "notfound", ...}` in the body, returns `None` immediately (no retry — matches the
handoff's explicit "Ikke retry på 404/notfound").

### User-Agent

Default: `f"mcp-openlibrary/{__version__} (+https://github.com/bjafl/mcp-tools)"`. Configurable
via `--user-agent` CLI flag / `OPENLIBRARY_USER_AGENT` env var (CLI wins, same precedence style
as the proxy flags in the other packages) for anyone who wants to add contact info to reach the
API's higher 3 req/s tier with attribution. The default does not embed any personal contact
info — it's a header sent to a third-party service, so nothing personally identifying goes in
unless the operator opts in via the override.

## 3. Normalization (`normalize.py`) — pure functions, no I/O

Ported/adapted from handoff §2.3–2.5 and the "Sjekkliste" in §10:

- `unwrap(v)`: `{"type": ..., "value": v}` → `v`; passes through plain strings unchanged. Used
  on `description`, `bio`, `first_sentence`, `notes`.
- `olid_kind(s: str) -> Literal["work", "edition", "author", "list"] | None`: regex-classifies
  `OL\d+[WMAL]`, used to auto-route `get_edition`'s single identifier param (OLID vs ISBN) and to
  give a clear validation error on malformed input instead of a wasted API call.
- `strip_missing_covers(ids: list[int]) -> list[int]`: filters out `-1` sentinel values.
- `cover_url(id_type: str, id_value: str, size: str = "M", kind: str = "book") -> str`: builds
  `https://covers.openlibrary.org/{b|a}/{id_type}/{id_value}-{size}.jpg?default=false`.
  `kind="book"` → `b/`, `kind="author"` → `a/`. Always appends `?default=false` per handoff §4
  ("ellers lagrer du tomme JPG-er" — a blank placeholder is worse than a clear 404).
- `subject_slug(s: str) -> str`: lowercases, replaces whitespace with `_`, for
  `search_subjects`'s convenience input (e.g. "science fiction" → `science_fiction`).
- `author_refs(obj: dict) -> list[str]`: normalizes both Work-shape
  (`[{"author": {"key": "/authors/OL..A"}}]`) and Edition-shape (`[{"key": "/authors/OL..A"}]`)
  author reference lists into a flat list of OLID strings.

## 4. Tools (`__main__.py`, registered on the `MCPServer` app)

All async, all go through `OpenLibraryClient.get_json()`. Single-object tools return a markdown
summary followed by a normalized JSON block; list tools return a markdown list (title + OLID per
item, no per-item JSON) plus a total-count/pagination line, to keep output size bounded on
searches with hundreds of hits.

1. **`search_books(query, fields=None, sort=None, limit=10, page=1)`** → `search.json`. `fields`
   defaults to the handoff's `DEFAULT_FIELDS` (§3.3) when not given — never `fields=*`. `limit`
   capped at 100 server-side (soft cap in the tool, not the API) to keep responses reasonable.
2. **`get_work(olid)`** → `works/{OLID}.json`. Validates `olid_kind(olid) == "work"` before
   calling. Authors shown as raw OLID refs (via `author_refs`), not resolved to names — resolving
   would mean N follow-up calls; the agent can call `get_author` itself if it wants a name.
3. **`get_edition(identifier)`** → accepts an edition OLID or an ISBN-10/13; routes to
   `books/{OLID}.json` or `isbn/{isbn}.json` respectively based on `olid_kind`/a simple ISBN
   digit-count check. Both are `follow_redirects=True` already at the client level.
4. **`search_authors(query, limit=10)`** → `search/authors.json`.
5. **`get_author(olid)`** → `authors/{OLID}.json`. Validates `olid_kind == "author"`.
6. **`get_author_works(olid, limit=50, offset=0)`** → `authors/{OLID}/works.json`. Surfaces
   `size` (total) and whether `links.next` exists so the agent knows to page further.
7. **`search_subjects(subject, details=False, limit=10, offset=0)`** → slugifies `subject` via
   `subject_slug`, then calls `subjects/{slug}.json`. `details=True` passes through
   `details=true` for the extra facet data (handoff §7 table).
8. **`get_cover_url(id_type, id_value, size="M", kind="book")`** → pure call into
   `normalize.cover_url`, no HTTP request, no rate limiting needed. `id_type` one of
   `id`/`olid`/`isbn`/`oclc`/`lccn` for `kind="book"`, or `id`/`olid` for `kind="author"`.

Each tool's docstring/`Field(description=...)` documents the "not found" behavior (returns a
plain "No work/author/... found for {id}" string, not an error) so the agent doesn't need to
special-case exceptions.

## 5. Error handling

- Network/HTTP-status failures that survive retries (`raise_for_status()` on a non-2xx that
  isn't 404/429/5xx, e.g. a `400`) propagate as exceptions — same as the existing two packages'
  `_fetch()`, which don't swallow errors either.
- `get_json() -> None` (404 or `notfound` body) is the *only* "not found" signal; tools turn it
  into a plain returned string, never raise for this case.
- Malformed identifiers (`olid_kind` returns `None` where a specific kind was expected) are
  rejected before any HTTP call, with a message naming the expected OLID pattern.

## 6. Testing

Same style as `test_proxy.py` in the existing packages — monkeypatched `httpx.AsyncClient`, no
live network calls.

- `test_ratelimit.py`: `TokenBucket.acquire()` spacing, using a monkeypatched `time.monotonic`/
  `time.sleep` (no real sleeping in tests).
- `test_normalize.py`: `unwrap` (str passthrough vs dict unwrap), `olid_kind` (all 4 patterns +
  invalid input), `strip_missing_covers`, `cover_url` (book vs author, all size/id_type
  combinations from the handoff's "same cover, five ways" table), `subject_slug`, `author_refs`
  (both Work-shape and Edition-shape inputs).
- `test_client.py`: `get_json` returns `None` on 404 and on `{"error":"notfound"}` body; retries
  on 429/5xx up to the cap then raises; does not retry on 404; passes the configured User-Agent.
- `test_tools.py`: one test per tool with a faked `OpenLibraryClient.get_json`, covering the
  happy path and the not-found path; `get_edition` routing test (OLID input vs ISBN input hits
  the right path); `get_cover_url` makes no HTTP call at all (assert the fake client is never
  invoked).

## 7. Documentation

- `README.md`: add a `mcp-openlibrary` row to the package table.
- New `packages/mcp-openlibrary/README.md` (the other two packages don't have per-package
  READMEs, but this one has 8 tools with distinct params worth documenting locally — short table
  of tool name → one-line description, plus a note on the two scoped-out features below).

## 8. Explicitly out of scope (v1)

- **Proxy support** — Open Library is a plain JSON API, not scraped HTML; can be added later by
  porting the same pattern from the other two packages if it turns out to be needed.
- **Response caching** — the handoff recommends it (§0, §9) since almost all data is static, but
  an interactive MCP tool doesn't repeat the same query enough in one session to justify the
  added complexity (TTL policy, storage location, invalidation) right now.
- **Bulk/dumps, `/api/books` legacy endpoint, `/search/inside.json` full-text search,
  `/recentchanges.json`, Lists/Your-Books (user-authenticated) endpoints** — not part of the
  agreed tool scope; the handoff documents them for completeness (§5.6, §8) but nothing in this
  design touches them.
- **Author-name resolution inside `get_work`/`get_edition`** — deliberate, to avoid N+1 calls;
  see §4.2.
