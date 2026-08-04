import asyncio

import httpx
import pytest

import mcp_recipe_scraper.__main__ as main_mod
from mcp_recipe_scraper.__main__ import _build_proxy_url, _resolve_proxy_config, _env_flag, _fetch, scrape_recipe


def test_resolve_proxy_config_cli_wins_over_env(monkeypatch):
    monkeypatch.setenv("MCP_PROXY_URL", "http://env-proxy:8888")
    monkeypatch.setenv("MCP_PROXY_USERNAME", "env-user")
    monkeypatch.setenv("MCP_PROXY_PASSWORD", "env-pass")

    result = _resolve_proxy_config("http://cli-proxy:9999", "cli-user", "cli-pass")

    assert result == "http://cli-user:cli-pass@cli-proxy:9999"


def test_resolve_proxy_config_env_wins_when_cli_is_none(monkeypatch):
    monkeypatch.setenv("MCP_PROXY_URL", "http://env-proxy:8888")
    monkeypatch.setenv("MCP_PROXY_USERNAME", "env-user")
    monkeypatch.setenv("MCP_PROXY_PASSWORD", "env-pass")

    result = _resolve_proxy_config(None, None, None)

    assert result == "http://env-user:env-pass@env-proxy:8888"


def test_resolve_proxy_config_fields_resolve_independently(monkeypatch):
    monkeypatch.setenv("MCP_PROXY_URL", "http://env-proxy:8888")
    monkeypatch.delenv("MCP_PROXY_USERNAME", raising=False)
    monkeypatch.delenv("MCP_PROXY_PASSWORD", raising=False)

    result = _resolve_proxy_config(None, "cli-user", None)

    assert result == "http://cli-user@env-proxy:8888"


def test_resolve_proxy_config_returns_none_without_url(monkeypatch):
    monkeypatch.delenv("MCP_PROXY_URL", raising=False)

    result = _resolve_proxy_config(None, None, None)

    assert result is None


def test_build_proxy_url_without_username():
    assert _build_proxy_url("http://proxy:8888", None, None) == "http://proxy:8888"


def test_build_proxy_url_with_username_and_password():
    result = _build_proxy_url("http://proxy:8888", "user", "pass")

    assert result == "http://user:pass@proxy:8888"


def test_env_flag_true_values(monkeypatch):
    for value in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv("MCP_PROXY_FALLBACK", value)
        assert _env_flag("MCP_PROXY_FALLBACK") is True


def test_env_flag_false_when_unset(monkeypatch):
    monkeypatch.delenv("MCP_PROXY_FALLBACK", raising=False)
    assert _env_flag("MCP_PROXY_FALLBACK") is False


class _FakeAsyncClient:
    """Records the proxy/timeout it was constructed with and delegates .get() to a callback."""

    def __init__(self, get_impl, follow_redirects=True, timeout=None, proxy=None):
        self.proxy = proxy
        self.timeout = timeout
        self._get_impl = get_impl

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, headers=None):
        return await self._get_impl(self.proxy, url)


def test_fetch_uses_proxy_when_fallback_disabled(monkeypatch):
    monkeypatch.setattr(main_mod, "PROXY", "http://proxy:8888")
    monkeypatch.setattr(main_mod, "PROXY_FALLBACK", False)
    seen_proxies = []

    async def get_impl(proxy, url):
        seen_proxies.append(proxy)
        return httpx.Response(200, request=httpx.Request("GET", url), text="ok")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(get_impl, **kw))

    response, used_fallback = asyncio.run(_fetch("http://example.com"))

    assert used_fallback is False
    assert response.text == "ok"
    assert seen_proxies == ["http://proxy:8888"]


def test_fetch_falls_back_on_connect_error(monkeypatch):
    monkeypatch.setattr(main_mod, "PROXY", "http://proxy:8888")
    monkeypatch.setattr(main_mod, "PROXY_FALLBACK", True)
    seen_proxies = []

    async def get_impl(proxy, url):
        seen_proxies.append(proxy)
        if proxy:
            raise httpx.ConnectError("boom", request=httpx.Request("GET", url))
        return httpx.Response(200, request=httpx.Request("GET", url), text="direct ok")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(get_impl, **kw))

    response, used_fallback = asyncio.run(_fetch("http://example.com"))

    assert used_fallback is True
    assert response.text == "direct ok"
    assert seen_proxies == ["http://proxy:8888", None]


def test_fetch_uses_short_connect_timeout_on_proxied_leg(monkeypatch):
    monkeypatch.setattr(main_mod, "PROXY", "http://proxy:8888")
    monkeypatch.setattr(main_mod, "PROXY_FALLBACK", True)
    seen_clients = []

    async def get_impl(proxy, url):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", url))

    class _CapturingFakeAsyncClient(_FakeAsyncClient):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            seen_clients.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _CapturingFakeAsyncClient(get_impl, **kw))

    with pytest.raises(httpx.ConnectError):
        asyncio.run(_fetch("http://example.com"))

    proxied_client, direct_client = seen_clients
    assert isinstance(proxied_client.timeout, httpx.Timeout)
    assert proxied_client.timeout.connect == main_mod.PROXY_FALLBACK_TIMEOUT
    assert proxied_client.timeout.read == main_mod.TIMEOUT
    assert direct_client.timeout == main_mod.TIMEOUT


def test_fetch_does_not_fall_back_on_read_timeout(monkeypatch):
    monkeypatch.setattr(main_mod, "PROXY", "http://proxy:8888")
    monkeypatch.setattr(main_mod, "PROXY_FALLBACK", True)
    call_count = 0

    async def get_impl(proxy, url):
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("slow target", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(get_impl, **kw))

    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(_fetch("http://example.com"))

    assert call_count == 1


def test_fetch_does_not_fall_back_on_http_status_error(monkeypatch):
    monkeypatch.setattr(main_mod, "PROXY", "http://proxy:8888")
    monkeypatch.setattr(main_mod, "PROXY_FALLBACK", True)
    call_count = 0

    async def get_impl(proxy, url):
        nonlocal call_count
        call_count += 1
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(get_impl, **kw))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_fetch("http://example.com"))

    assert call_count == 1


class _FakeScraper:
    def title(self):
        return "Test Recipe"

    def yields(self):
        return "4 servings"

    def ingredients(self):
        return ["a", "b"]

    def instructions(self):
        return "Do it"

    def nutrients(self):
        return {"calories": "100"}

    def to_json(self):
        return {"title": "Test Recipe"}


def test_scrape_recipe_prepends_note_when_fallback_used(monkeypatch):
    async def fake_fetch(url):
        return httpx.Response(200, request=httpx.Request("GET", url), text="<html></html>"), True

    monkeypatch.setattr(main_mod, "_fetch", fake_fetch)
    monkeypatch.setattr(main_mod, "scrape_html", lambda html, org_url, supported_only: _FakeScraper())

    result = asyncio.run(scrape_recipe(url="http://example.com", supported_only=False))

    assert result.startswith("> Note: the proxy did not respond")
    assert "Test Recipe" in result


def test_scrape_recipe_no_note_without_fallback(monkeypatch):
    async def fake_fetch(url):
        return httpx.Response(200, request=httpx.Request("GET", url), text="<html></html>"), False

    monkeypatch.setattr(main_mod, "_fetch", fake_fetch)
    monkeypatch.setattr(main_mod, "scrape_html", lambda html, org_url, supported_only: _FakeScraper())

    result = asyncio.run(scrape_recipe(url="http://example.com", supported_only=False))

    assert not result.startswith("> Note:")
