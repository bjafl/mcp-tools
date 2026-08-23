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


def test_get_api_non_json_error_message_includes_status_code(monkeypatch):
    async def get_impl(url, params):
        return _FakeResponse(401, content_type="text/html")

    client, fake = _make_client(monkeypatch, get_impl)

    with pytest.raises(SteamAPIError) as exc_info:
        asyncio.run(client.get_api("ISteamUser/GetFriendList/v1", steamid="123"))

    assert exc_info.value.status_code == 401
    assert "401" in str(exc_info.value)
    assert "text/html" in str(exc_info.value)


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
