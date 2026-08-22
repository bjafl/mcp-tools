import pytest

import mcp_steamapi.__main__ as main_mod
from mcp_steamapi.__main__ import _resolve_api_key, _client
from mcp_steamapi.client import SteamClient


def test_resolve_api_key_returns_env_value(monkeypatch):
    monkeypatch.setenv("STEAM_API_KEY", "abc123")
    assert _resolve_api_key() == "abc123"


def test_resolve_api_key_exits_when_unset(monkeypatch):
    monkeypatch.delenv("STEAM_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        _resolve_api_key()
    assert exc_info.value.code == 1


def test_client_lazily_constructs_when_none(monkeypatch):
    monkeypatch.setenv("STEAM_API_KEY", "abc123")
    monkeypatch.setattr(main_mod, "CLIENT", None)

    client = _client()

    assert isinstance(client, SteamClient)


def test_client_returns_existing_when_set(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(main_mod, "CLIENT", sentinel)

    result = _client()

    assert result is sentinel
