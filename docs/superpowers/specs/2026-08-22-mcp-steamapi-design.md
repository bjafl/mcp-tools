# mcp-steamapi — new MCP server package

**Status:** Approved
**Date:** 2026-08-22

## Summary

A new package, `mcp-steamapi`, exposing the Steam Web API as 16 MCP tools covering the
achievement-mapping use case documented in `handoff-steamapi.md` (repo root): resolving a
player's identity, listing their owned games, and joining a game's achievement schema against a
player's unlocks and global rarity — plus numeric stats, profile/social lookups, and store
metadata as explicitly requested scope.

Same package shape as `mcp-openlibrary` (`src/` layout, `uv_build`, argparse CLI, one file per
concern), but with two things `mcp-openlibrary` didn't need: a **second rate-limited host**
(`store.steampowered.com`, unofficial, much stricter limit) and a **richer error-handling
matrix** — Steam's failure modes don't collapse into one 404/`None` sentinel the way Open
Library's do; a private profile is a silent `200` + `{}` on one endpoint and an `HTTP 403` +
`success: false` on another (handoff §7).

**Learned from the `mcp-openlibrary` final review:** that branch shipped a real bug — a
synchronous `TokenBucket`/retry-backoff using `time.sleep()` inside `async def` MCP tool
handlers, which blocks the whole server's event loop (all MCP tools are awaited directly, never
in a thread pool). This design specifies `TokenBucket.acquire()` as `async def` using
`await asyncio.sleep(...)` from the start, and the client's retry backoff the same way — no
synchronous sleep anywhere in this package's async code paths.

## 1. Package layout

```
packages/mcp-steamapi/
  pyproject.toml
  src/mcp_steamapi/
    __init__.py        # from mcp_steamapi.__main__ import main
    __main__.py         # argparse CLI, MCPServer app, 16 tool functions, app.run()
    client.py            # SteamClient: two TokenBuckets, get_json() with Steam-specific error handling
    ratelimit.py           # TokenBucket — async from the start (see note above)
    cache.py                # TTLCache — sync in-memory dict+TTL, used only for GetAppList/GetSchemaForGame
    normalize.py             # steamid64 validation, visibility/persona-state labels, icon URL builder,
                              # minutes formatting, per-endpoint "is this the private/no-stats shape" helpers
  tests/
    test_normalize.py
    test_ratelimit.py
    test_cache.py
    test_client.py
    test_cli.py
    test_achievement_tools.py     # the 7 achievements-core tools
    test_stats_social_tools.py    # get_user_stats_for_game + the 4 profile/social tools
    test_store_tools.py           # the 4 store/metadata tools
```

`pyproject.toml`: same shape as `mcp-recipe-scraper`/`mcp-openlibrary` (`uv_build` backend,
`requires-python = ">=3.12"`, `[project.scripts] mcp-steamapi = "mcp_steamapi:main"`).
Dependencies: `mcp[cli]>=2.0.0,<3`, `httpx>=0.27,<0.29`, `pydantic>=2,<3` — same pins, no new
libraries (in-memory cache needs nothing beyond the stdlib).

Root `pyproject.toml` and `README.md` get the new package added, per the existing "Adding a new
package" checklist.

## 2. HTTP layer (`ratelimit.py`, `client.py`)

### `TokenBucket` — async

```python
class TokenBucket:
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

No lock: there's no `await` between reading and writing `self._next`, so a single-threaded
asyncio event loop can't interleave two callers mid-update — the same reasoning the
`mcp-openlibrary` fix wave landed on, applied here from the start instead of after a review
catches it.

### `SteamClient`

Two buckets: `api.steampowered.com` at **5 req/s** (handoff's "≤5–10/s" recommendation, picking
the conservative end), `store.steampowered.com` at **0.5 req/s** (≈150 calls/5min — safely under
the ≈200/5min community-observed limit; the handoff's literal "≤1/s" would sit right at the
edge).

```python
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
                    raise SteamAPIError(f"Steam API error {response.status_code} after retries", response.status_code)
                await asyncio.sleep(_retry_delay(response, attempt))
                continue

            content_type = response.headers.get("content-type", "")
            if response.status_code == 403 and "application/json" not in content_type:
                raise SteamAPIError("Steam API rejected the request (403) — check STEAM_API_KEY", 403)

            if not response.content and attempt == 0:
                await asyncio.sleep(1.0)
                continue

            if "application/json" not in content_type:
                raise SteamAPIError(f"Steam API returned non-JSON content ({content_type or 'unknown'})", response.status_code)

            return response.json()
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

**Deliberate design point:** `_get()` raises `SteamAPIError` only for the genuinely fatal/
unrecoverable cases (bad key, retries exhausted, unexpected non-JSON body). It does **not**
raise for a `success: false` JSON body, a `{"response": {}}` empty-private response, or a `400`
"no stats" response — those are valid, parseable responses whose *meaning* is endpoint-specific
(§7's matrix has at least 4 different "this is fine, just tell the agent why" shapes). Each tool
function interprets its own response shape via small `normalize.py` helpers, rather than the
client trying to guess a one-size-fits-all sentinel the way `mcp-openlibrary`'s 404→`None` could.

## 3. Caching (`cache.py`) — in-memory only

```python
class TTLCache:
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

Plain sync class (no I/O, no `await` needed — `time.monotonic()` reads are instant, unlike
`time.sleep()`). Two instances live on the `SteamClient` or as module globals in `__main__.py`:
one for `GetAppList` (TTL 7 days, single key since it's one global list), one for
`GetSchemaForGame` (TTL 7 days, keyed by `f"{appid}:{language or ''}"`).

**Deliberately no disk persistence** — `tiny-metamcp` (this package's primary intended host)
keeps child MCP server processes running long-term rather than spawning one per call
(`packages/aggregator/src/aggregator/child_manager.py`'s supervisor-task model), so an
in-process cache is effective for the process's whole lifetime. A lost cache on restart costs one
re-fetch of `GetAppList`/an already-seen schema — not worth the added complexity (cache
directory, permissions, staleness-across-restarts) for v1.

## 4. Normalization (`normalize.py`) — pure functions, no I/O

- `is_valid_steamid64(s: str) -> bool`: `s.isdigit() and len(s) == 17`.
- `steam_icon_url(appid: int, img_icon_url: str) -> str`: builds
  `https://media.steampowered.com/steamcommunity/public/images/apps/{appid}/{img_icon_url}.jpg`.
- `minutes_to_hours(minutes: int) -> float`: `round(minutes / 60, 1)` — display helper for
  playtime, which the API always returns in minutes (handoff §3.1).
- `visibility_label(state: int) -> str`: maps `communityvisibilitystate` (`1`→"private/friends
  only", `3`→"public", else "unknown") per handoff §4.2.
- `persona_state_label(state: int) -> str`: maps `personastate` 0–6 to the labels in handoff
  §4.2 ("Offline", "Online", "Busy", "Away", "Snooze", "Looking to trade", "Looking to play").
- `is_empty_owned_games_response(data: dict) -> bool`: detects `GetOwnedGames`'s silent-private
  shape — `data.get("response", {})` has no `"games"` key (handoff §3.1's "vanligste stille
  feilen").
- `player_achievements_error(status_code: int, data: dict) -> str | None`: given a
  `GetPlayerAchievements` response, returns a human message for the private-profile
  (`403`+`success:false`) or no-stats (`400`, or `200`+`success:false`) cases, or `None` if the
  response is a genuine success — used by `get_player_achievements` to decide whether to format
  achievement data or return an explanatory message instead of raising.

## 5. Tools (`__main__.py`, registered on the `MCPServer` app) — 16 total

All async, all go through `SteamClient`. Single-object tools return a markdown summary + a
normalized JSON block; list tools return a markdown list with the join-keys the agent needs to
chain into a follow-up call (steamid, appid, achievement `name`/`apiname`).

### Achievements core (7)

1. **`resolve_vanity_url(vanity_url)`** → `ISteamUser/ResolveVanityURL/v1`. `success: 42` → clear
   "no match" message, not an error.
2. **`get_player_summary(steamid)`** → `ISteamUser/GetPlayerSummaries/v2` (single id — batch
   lookups are out of scope for v1, see §7). Surfaces `communityvisibilitystate` via
   `visibility_label()` explicitly and prominently — this is the preflight-check tool the design
   discussion asked for.
3. **`get_owned_games(steamid, include_played_free_games=False)`** → `IPlayerService/
   GetOwnedGames/v1` with `include_appinfo=1` always hardcoded (the tool is useless without it,
   per handoff §3.1). Surfaces `has_community_visible_stats` per game — the best available hint
   for "worth calling the schema for". `is_empty_owned_games_response()` → clear "profile or game
   details aren't public" message instead of an empty list.
4. **`get_recently_played_games(steamid, count=0)`** → `IPlayerService/GetRecentlyPlayedGames/v1`.
5. **`get_game_achievements_schema(appid, language=None)`** → `ISteamUserStats/
   GetSchemaForGame/v2`. **Cached** (TTLCache, 7 days, key `f"{appid}:{language or ''}"`). No
   `availableGameStats` in the response → clear "this game has no achievements" message, not an
   error (handoff §2.1 — this is a normal, expected shape for many appids).
6. **`get_player_achievements(steamid, appid, language=None)`** → `ISteamUserStats/
   GetPlayerAchievements/v1`. Uses `player_achievements_error()` to turn the private/no-stats
   cases into a plain message rather than surfacing a raw API error.
7. **`get_global_achievement_percentages(appid)`** → `ISteamUserStats/
   GetGlobalAchievementPercentagesForApp/v2`. No key (`needs_key=False`). **Parameter-name
   trap**: the API's query param is `gameid`, not `appid` — the tool's Python parameter is named
   `appid` for consistency with every other tool, but the client call maps it to `gameid=appid`
   explicitly (handoff §2.3 flags this by name as "merk feltnavnet").

### Numeric stats (1)

8. **`get_user_stats_for_game(steamid, appid, language=None)`** → `ISteamUserStats/
   GetUserStatsForGame/v2`. Tool description notes this endpoint's `achievements` list lacks
   `unlocktime` and is a worse source than tool 6 for achievement status — its value is the
   `stats` list for progression tracking ("812/1000").

### Profile & social (4)

9. **`get_steam_level(steamid)`** → `IPlayerService/GetSteamLevel/v1`.
10. **`get_badges(steamid)`** → `IPlayerService/GetBadges/v1`.
11. **`get_friend_list(steamid)`** → `ISteamUser/GetFriendList/v1` (`relationship=friend`). Tool
    description carries handoff §4.6's explicit warning: comparing achievements across a friend
    list multiplies call volume by `friends × games` — this tool only returns the raw list, no
    batch-comparison logic is built.
12. **`get_player_bans(steamid)`** → `ISteamUser/GetPlayerBans/v1` (single id — batch out of
    scope for v1, matching tool 2's scoping decision).

### Store/metadata (4) — via `SteamClient.get_store()`, the second rate-limited bucket

13. **`search_app_by_name(query, limit=10)`** → fetches+caches the full `ISteamApps/
    GetAppList/v2` (TTLCache, 7 days, single key), then does a case-insensitive substring match
    against `name` in-process, returns up to `limit` matches as `(appid, name)` pairs. Tool
    description notes the first call after a cache miss is slow (the list is tens of MB,
    200,000+ entries per handoff §5.1).
14. **`get_current_player_count(appid)`** → `ISteamUserStats/GetNumberOfCurrentPlayers/v1`. No
    key.
15. **`get_app_details(appid, country_code="no", language="norwegian")`** → unofficial
    `store.steampowered.com/api/appdetails`. Single `appid` only — handoff §5.3 warns the batch
    `appids` parameter unreliably returns `success: false` per app.
16. **`get_app_reviews(appid)`** → unofficial `store.steampowered.com/appreviews/{appid}`.

## 6. Error handling — mapped from handoff §7's matrix

| Situation | Client behavior | Tool-level behavior |
|---|---|---|
| Invalid API key | `SteamAPIError` raised (403 + non-JSON body) | Propagates — this is genuinely fatal, no tool can recover from a bad key |
| Private profile, `GetPlayerAchievements` | Returns the JSON body as-is (403 + JSON is not treated as an error by the client) | `player_achievements_error()` → plain "profile isn't public" message |
| Private game details, `GetOwnedGames` | Returns `{"response": {}}` as-is (200, valid JSON) | `is_empty_owned_games_response()` → plain "game details aren't public" message |
| Game without achievements | Returns response as-is on the first attempt — a plain `400` is not in `RETRY_STATUS_CODES` so it is never retried (see note below); a `200`+`success:false` body is likewise returned as-is | Tool-specific check → plain "no achievements for this game" message |
| Invalid/delisted appid | Same as above | Plain "not found / unavailable" message |
| Rate limit (429) | Retried with backoff, respects `Retry-After` | Transparent to the tool — only surfaces if retries exhaust |
| Steam down (5xx) | Retried with backoff | Transparent to the tool — only surfaces if retries exhaust |
| Empty 200 body | Retried once | Transparent to the tool |

**Note on 400s:** `RETRY_STATUS_CODES` is `{429, 500, 502, 503, 504}` — a plain `400` (the "game
without achievements" / "invalid appid" case) is *not* in that set, so `_get()` falls through to
the content-type check and returns the parsed JSON body directly on the first attempt, no retry.
This matches handoff §7's recommendation ("Marker spillet som «ingen achievements», hopp over,
ikke retry" / "Logg og hopp over") — a 400 here is a normal, expected outcome for a meaningful
fraction of appids, not a transient failure worth retrying.

## 7. Testing

Same style as `mcp-openlibrary` — monkeypatched `httpx.AsyncClient`, no live network calls, and
(having learned from that package's final-review finding) `asyncio.sleep` patched with an async
no-op rather than `time.sleep`, from the first test written.

- `test_ratelimit.py`: `TokenBucket.acquire()` spacing, driven via `asyncio.run(...)`, with
  `asyncio.sleep` monkeypatched to a no-op and `time.monotonic` faked — mirrors
  `mcp-openlibrary`'s *fixed* `ratelimit.py`, not its original (buggy) one.
- `test_cache.py`: `TTLCache` returns `None` on miss/expiry, returns the value before expiry,
  re-fetches after expiry — driven with a faked `time.monotonic`.
- `test_client.py`: `SteamAPIError` raised on non-JSON 403, on retry exhaustion, on unexpected
  non-JSON content-type; retried on 429/5xx with `Retry-After` honored when present; *not*
  retried on 400; empty-body-once retry; a `success: false` JSON body on any status is returned
  as data, not raised.
- `test_normalize.py`: all 7 pure functions, including both branches of
  `is_empty_owned_games_response` and the private/no-stats/success branches of
  `player_achievements_error`.
- `test_cli.py`: `STEAM_API_KEY` env var is required (clear startup error if missing — no
  CLI-flag path exists, per the design decision).
- `test_achievement_tools.py` / `test_stats_social_tools.py` / `test_store_tools.py`: one test
  per tool per meaningful branch (happy path + each documented error shape), following
  `mcp-openlibrary`'s `_FakeClient`-via-`monkeypatch` pattern. `search_app_by_name` gets a test
  confirming the second call within the TTL window doesn't re-fetch `GetAppList` (cache hit).

## 8. Documentation

- `README.md`: add a `mcp-steamapi` row to the package table.
- New `packages/mcp-steamapi/README.md`: tool table (16 rows), a note on `STEAM_API_KEY`
  (env-var-only, why), a note on the two rate-limited hosts, and a note on the in-memory-only
  cache (and its `tiny-metamcp` rationale).

## 9. Explicitly out of scope (v1)

- **Disk-persistent caching** — in-memory only, per §3's rationale.
- **Batch lookups** for `get_player_summary`/`get_player_bans` (Steam supports up to 100
  comma-separated steamids on both) — single-id only in v1; batching is a mechanical addition
  later if needed, not a design blocker now.
- **Friend-list achievement comparison** — `get_friend_list` returns the raw list only; no
  `friends × games` fan-out logic is built, per the handoff's explicit call-volume warning.
- **`IPlayerService/GetGameAchievements/v1`** (handoff §2.5) — "less documented than §2.1/§2.3",
  the handoff itself recommends treating it as a future optimization, not a v1 primary.
- **`IPlayerService/GetCommunityBadgeProgress/v1`** (handoff §4.5) — per-badge quest detail,
  more niche than the 4 profile/social tools already in scope.
- **Partner/publisher API** (`partner.steam-api.com`) — explicitly out of scope per the handoff
  itself (§1).
- **CLI flag for the API key** — env var only, per the design decision in §"API key" above.
- **Proxy support** — not requested; Steam's APIs are plain JSON/HTTP, same reasoning as
  `mcp-openlibrary`.
