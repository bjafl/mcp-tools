import pytest

import mcp_backblaze.__main__ as main_mod
from mcp_backblaze.__main__ import _client, _resolve_credentials
from mcp_backblaze.client import B2Client


def test_resolve_credentials_returns_env_values(monkeypatch):
    monkeypatch.setenv("B2_APPLICATION_KEY_ID", "key-id")
    monkeypatch.setenv("B2_APPLICATION_KEY", "app-key")

    assert _resolve_credentials() == ("key-id", "app-key")


def test_resolve_credentials_exits_when_key_id_unset(monkeypatch):
    monkeypatch.delenv("B2_APPLICATION_KEY_ID", raising=False)
    monkeypatch.setenv("B2_APPLICATION_KEY", "app-key")

    with pytest.raises(SystemExit) as exc_info:
        _resolve_credentials()
    assert exc_info.value.code == 1


def test_resolve_credentials_exits_when_key_unset(monkeypatch):
    monkeypatch.setenv("B2_APPLICATION_KEY_ID", "key-id")
    monkeypatch.delenv("B2_APPLICATION_KEY", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        _resolve_credentials()
    assert exc_info.value.code == 1


def test_client_lazily_constructs_when_none(monkeypatch):
    monkeypatch.setenv("B2_APPLICATION_KEY_ID", "key-id")
    monkeypatch.setenv("B2_APPLICATION_KEY", "app-key")
    monkeypatch.setattr(main_mod, "CLIENT", None)

    client = _client()

    assert isinstance(client, B2Client)


def test_client_returns_existing_when_set(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(main_mod, "CLIENT", sentinel)

    result = _client()

    assert result is sentinel
