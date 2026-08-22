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
