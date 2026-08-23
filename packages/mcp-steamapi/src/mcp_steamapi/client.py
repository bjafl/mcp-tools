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
                    f"Steam API returned non-JSON content ({content_type or 'unknown'}) "
                    f"[HTTP {response.status_code}]",
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
