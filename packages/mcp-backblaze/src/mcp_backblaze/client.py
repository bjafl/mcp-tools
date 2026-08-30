import asyncio
import base64
import hashlib
import time
import urllib.parse
from dataclasses import dataclass

import httpx

AUTH_URL = "https://api.backblazeb2.com/b2api/v4/b2_authorize_account"
TOKEN_TTL_SECONDS = 23 * 60 * 60  # docs don't state an expiry; 23h leaves margin under the ~24h token lifetime
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5


class B2ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass
class _AuthState:
    token: str
    account_id: str
    api_url: str
    download_url: str
    expires_at: float


def _encode_file_name(file_name: str) -> str:
    return urllib.parse.quote(file_name, safe="/")


class B2Client:
    def __init__(self, key_id: str, application_key: str):
        self._key_id = key_id
        self._key = application_key
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True)
        self._auth: _AuthState | None = None

    async def _authorize(self) -> _AuthState:
        if self._auth is not None and time.time() < self._auth.expires_at:
            return self._auth

        credentials = base64.b64encode(f"{self._key_id}:{self._key}".encode()).decode()
        response = await self._request("GET", AUTH_URL, headers={"Authorization": f"Basic {credentials}"})
        data = response.json()
        storage = data["apiInfo"]["storageApi"]
        self._auth = _AuthState(
            token=data["authorizationToken"],
            account_id=data["accountId"],
            api_url=storage["apiUrl"],
            download_url=storage["downloadUrl"],
            expires_at=time.time() + TOKEN_TTL_SECONDS,
        )
        return self._auth

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        for attempt in range(MAX_ATTEMPTS):
            response = await self._http.request(method, url, **kwargs)
            if response.status_code in RETRY_STATUS_CODES:
                if attempt == MAX_ATTEMPTS - 1:
                    raise self._error_from_response(response)
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code >= 400:
                raise self._error_from_response(response)
            return response
        raise B2ApiError(f"gave up after {MAX_ATTEMPTS} attempts: {url}")

    @staticmethod
    def _error_from_response(response: httpx.Response) -> B2ApiError:
        try:
            data = response.json()
        except ValueError:
            data = {}
        code = data.get("code")
        message = data.get("message") or response.text or response.reason_phrase
        return B2ApiError(message, response.status_code, code)

    async def list_buckets(self) -> list[dict]:
        auth = await self._authorize()
        response = await self._request(
            "POST",
            f"{auth.api_url}/b2api/v4/b2_list_buckets",
            headers={"Authorization": auth.token},
            json={"accountId": auth.account_id},
        )
        return response.json()["buckets"]

    async def list_files(
        self,
        bucket_id: str,
        prefix: str | None = None,
        max_file_count: int = 100,
        start_file_name: str | None = None,
    ) -> dict:
        auth = await self._authorize()
        params: dict[str, object] = {"bucketId": bucket_id, "maxFileCount": max_file_count}
        if prefix:
            params["prefix"] = prefix
        if start_file_name:
            params["startFileName"] = start_file_name
        response = await self._request(
            "GET",
            f"{auth.api_url}/b2api/v4/b2_list_file_names",
            headers={"Authorization": auth.token},
            params=params,
        )
        return response.json()

    async def get_upload_url(self, bucket_id: str) -> dict:
        auth = await self._authorize()
        response = await self._request(
            "GET",
            f"{auth.api_url}/b2api/v4/b2_get_upload_url",
            headers={"Authorization": auth.token},
            params={"bucketId": bucket_id},
        )
        return response.json()

    async def upload_bytes(
        self, bucket_id: str, file_name: str, data: bytes, content_type: str = "b2/x-auto"
    ) -> dict:
        upload_info = await self.get_upload_url(bucket_id)
        response = await self._request(
            "POST",
            upload_info["uploadUrl"],
            headers={
                "Authorization": upload_info["authorizationToken"],
                "X-Bz-File-Name": _encode_file_name(file_name),
                "Content-Type": content_type,
                "X-Bz-Content-Sha1": hashlib.sha1(data).hexdigest(),
            },
            content=data,
        )
        return response.json()

    async def download_file(self, bucket_name: str, file_name: str) -> bytes:
        auth = await self._authorize()
        response = await self._request(
            "GET",
            f"{auth.download_url}/file/{bucket_name}/{_encode_file_name(file_name)}",
            headers={"Authorization": auth.token},
        )
        return response.content

    async def delete_file(self, file_name: str, file_id: str) -> dict:
        auth = await self._authorize()
        response = await self._request(
            "POST",
            f"{auth.api_url}/b2api/v4/b2_delete_file_version",
            headers={"Authorization": auth.token},
            json={"fileName": file_name, "fileId": file_id},
        )
        return response.json()

    async def get_file_info(self, file_id: str) -> dict:
        auth = await self._authorize()
        response = await self._request(
            "GET",
            f"{auth.api_url}/b2api/v4/b2_get_file_info",
            headers={"Authorization": auth.token},
            params={"fileId": file_id},
        )
        return response.json()

    async def aclose(self) -> None:
        await self._http.aclose()
