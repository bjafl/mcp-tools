from mcp_fetch_select.__main__ import _build_proxy_url, _resolve_proxy_config


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
