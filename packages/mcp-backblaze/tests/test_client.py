import asyncio

import httpx
import pytest

import mcp_backblaze.client as client_mod
from mcp_backblaze.client import B2ApiError, B2Client


class _FakeResponse:
    def __init__(self, status_code, json_data=None, content=b"", text="", reason_phrase=""):
        self.status_code = status_code
        self._json_data = json_data
        self.content = content
        self.text = text
        self.reason_phrase = reason_phrase

    def json(self):
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, request_impl):
        self._request_impl = request_impl
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return await self._request_impl(method, url, **kwargs)

    async def aclose(self):
        pass


AUTH_RESPONSE = {
    "accountId": "acct-1",
    "authorizationToken": "auth-token",
    "apiInfo": {
        "storageApi": {
            "apiUrl": "https://api000.example.com",
            "downloadUrl": "https://f000.example.com",
        }
    },
}


def _make_client(monkeypatch, request_impl, sleeps=None):
    fake = _FakeAsyncClient(request_impl)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)

    async def fake_sleep(s):
        if sleeps is not None:
            sleeps.append(s)

    monkeypatch.setattr(client_mod.asyncio, "sleep", fake_sleep)
    return B2Client(key_id="key-id", application_key="app-key"), fake


def test_authorize_sends_basic_auth_header(monkeypatch):
    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(200, {"buckets": []})

    client, fake = _make_client(monkeypatch, request_impl)

    asyncio.run(client.list_buckets())

    auth_call = fake.calls[0]
    assert auth_call[1] == "https://api.backblazeb2.com/b2api/v4/b2_authorize_account"
    assert auth_call[2]["headers"]["Authorization"].startswith("Basic ")


def test_authorize_caches_token_until_expiry(monkeypatch):
    calls = {"n": 0}

    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            calls["n"] += 1
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(200, {"buckets": []})

    client, fake = _make_client(monkeypatch, request_impl)

    asyncio.run(client.list_buckets())
    asyncio.run(client.list_buckets())

    assert calls["n"] == 1


def test_authorize_reauthorizes_after_expiry(monkeypatch):
    calls = {"n": 0}
    now = {"t": 1000.0}

    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            calls["n"] += 1
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(200, {"buckets": []})

    client, fake = _make_client(monkeypatch, request_impl)
    monkeypatch.setattr(client_mod.time, "time", lambda: now["t"])

    asyncio.run(client.list_buckets())
    now["t"] += 24 * 60 * 60
    asyncio.run(client.list_buckets())

    assert calls["n"] == 2


def test_list_buckets_returns_buckets(monkeypatch):
    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(200, {"buckets": [{"bucketId": "b1", "bucketName": "photos"}]})

    client, fake = _make_client(monkeypatch, request_impl)

    result = asyncio.run(client.list_buckets())

    assert result == [{"bucketId": "b1", "bucketName": "photos"}]


def test_list_files_omits_optional_params_when_absent(monkeypatch):
    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(200, {"files": [], "nextFileName": None})

    client, fake = _make_client(monkeypatch, request_impl)

    asyncio.run(client.list_files("bucket-1"))

    list_call = fake.calls[1]
    assert "prefix" not in list_call[2]["params"]
    assert "startFileName" not in list_call[2]["params"]
    assert list_call[2]["params"]["bucketId"] == "bucket-1"
    assert list_call[2]["params"]["maxFileCount"] == 100


def test_list_files_includes_prefix_and_start_file_name(monkeypatch):
    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(200, {"files": [], "nextFileName": None})

    client, fake = _make_client(monkeypatch, request_impl)

    asyncio.run(client.list_files("bucket-1", prefix="photos/", start_file_name="cat.jpg"))

    list_call = fake.calls[1]
    assert list_call[2]["params"]["prefix"] == "photos/"
    assert list_call[2]["params"]["startFileName"] == "cat.jpg"


def test_get_upload_url_returns_response(monkeypatch):
    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(200, {"uploadUrl": "https://up.example.com", "authorizationToken": "up-tok"})

    client, fake = _make_client(monkeypatch, request_impl)

    result = asyncio.run(client.get_upload_url("bucket-1"))

    assert result["uploadUrl"] == "https://up.example.com"


def test_upload_bytes_computes_sha1_and_encodes_filename(monkeypatch):
    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        if "get_upload_url" in url:
            return _FakeResponse(200, {"uploadUrl": "https://up.example.com/x", "authorizationToken": "up-tok"})
        return _FakeResponse(200, {"fileId": "f1", "fileName": "photos/cat.jpg"})

    client, fake = _make_client(monkeypatch, request_impl)

    result = asyncio.run(client.upload_bytes("bucket-1", "photos/cat.jpg", b"hello", "text/plain"))

    upload_call = fake.calls[-1]
    assert upload_call[1] == "https://up.example.com/x"
    assert upload_call[2]["headers"]["X-Bz-File-Name"] == "photos/cat.jpg"
    assert upload_call[2]["headers"]["Content-Type"] == "text/plain"
    assert upload_call[2]["headers"]["Authorization"] == "up-tok"
    assert upload_call[2]["headers"]["X-Bz-Content-Sha1"] == "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"
    assert upload_call[2]["content"] == b"hello"
    assert result["fileId"] == "f1"


def test_download_file_returns_raw_bytes(monkeypatch):
    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(200, content=b"binary-data")

    client, fake = _make_client(monkeypatch, request_impl)

    result = asyncio.run(client.download_file("my-bucket", "photos/cat.jpg"))

    download_call = fake.calls[1]
    assert download_call[1] == "https://f000.example.com/file/my-bucket/photos/cat.jpg"
    assert result == b"binary-data"


def test_delete_file_posts_file_name_and_id(monkeypatch):
    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(200, {"fileId": "f1", "fileName": "cat.jpg"})

    client, fake = _make_client(monkeypatch, request_impl)

    result = asyncio.run(client.delete_file("cat.jpg", "f1"))

    delete_call = fake.calls[1]
    assert delete_call[2]["json"] == {"fileName": "cat.jpg", "fileId": "f1"}
    assert result == {"fileId": "f1", "fileName": "cat.jpg"}


def test_get_file_info_returns_metadata(monkeypatch):
    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(200, {"fileId": "f1", "fileName": "cat.jpg", "contentLength": 42})

    client, fake = _make_client(monkeypatch, request_impl)

    result = asyncio.run(client.get_file_info("f1"))

    assert result["contentLength"] == 42


def test_raises_b2_api_error_on_400_with_code_and_message(monkeypatch):
    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(400, {"code": "bad_request", "message": "bucketId is invalid"})

    client, fake = _make_client(monkeypatch, request_impl)

    with pytest.raises(B2ApiError) as exc_info:
        asyncio.run(client.list_files("bad-bucket"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "bad_request"
    assert "bucketId is invalid" in str(exc_info.value)


def test_retries_on_503_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResponse(503, text="unavailable")
        return _FakeResponse(200, {"buckets": []})

    client, fake = _make_client(monkeypatch, request_impl)

    result = asyncio.run(client.list_buckets())

    assert result == []
    assert calls["n"] == 3


def test_does_not_retry_on_400(monkeypatch):
    calls = {"n": 0}

    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        calls["n"] += 1
        return _FakeResponse(400, {"code": "bad_request", "message": "nope"})

    client, fake = _make_client(monkeypatch, request_impl)

    with pytest.raises(B2ApiError):
        asyncio.run(client.list_buckets())

    assert calls["n"] == 1


def test_raises_after_max_attempts(monkeypatch):
    async def request_impl(method, url, **kwargs):
        if "authorize_account" in url:
            return _FakeResponse(200, AUTH_RESPONSE)
        return _FakeResponse(503, text="unavailable")

    client, fake = _make_client(monkeypatch, request_impl)

    with pytest.raises(B2ApiError):
        asyncio.run(client.list_buckets())
