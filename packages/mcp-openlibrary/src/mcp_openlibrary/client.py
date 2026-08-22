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
