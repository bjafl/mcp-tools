import mcp_steamapi.cache as cache_mod
from mcp_steamapi.cache import TTLCache


def test_get_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: 100.0)
    cache = TTLCache(ttl_seconds=10)

    assert cache.get("k") is None


def test_get_returns_value_before_expiry(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock["t"])
    cache = TTLCache(ttl_seconds=10)

    cache.set("k", "v")
    clock["t"] = 105.0

    assert cache.get("k") == "v"


def test_get_returns_none_after_expiry(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock["t"])
    cache = TTLCache(ttl_seconds=10)

    cache.set("k", "v")
    clock["t"] = 111.0

    assert cache.get("k") is None


def test_expired_entry_is_evicted_from_store(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock["t"])
    cache = TTLCache(ttl_seconds=10)

    cache.set("k", "v")
    clock["t"] = 111.0
    cache.get("k")

    assert "k" not in cache._store
