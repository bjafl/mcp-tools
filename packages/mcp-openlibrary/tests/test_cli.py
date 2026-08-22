from mcp_openlibrary.__main__ import _resolve_user_agent, DEFAULT_USER_AGENT


def test_resolve_user_agent_cli_wins(monkeypatch):
    monkeypatch.setenv("OPENLIBRARY_USER_AGENT", "env-agent")
    assert _resolve_user_agent("cli-agent") == "cli-agent"


def test_resolve_user_agent_env_wins_when_cli_none(monkeypatch):
    monkeypatch.setenv("OPENLIBRARY_USER_AGENT", "env-agent")
    assert _resolve_user_agent(None) == "env-agent"


def test_resolve_user_agent_default_when_neither_set(monkeypatch):
    monkeypatch.delenv("OPENLIBRARY_USER_AGENT", raising=False)
    assert _resolve_user_agent(None) == DEFAULT_USER_AGENT
