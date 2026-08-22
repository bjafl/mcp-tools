import asyncio

import mcp_openlibrary.ratelimit as ratelimit_mod
from mcp_openlibrary.ratelimit import TokenBucket


def _patch_sleep(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(ratelimit_mod.asyncio, "sleep", fake_sleep)
    return sleeps


def test_first_acquire_does_not_sleep(monkeypatch):
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: 100.0)
    sleeps = _patch_sleep(monkeypatch)

    bucket = TokenBucket(rate_per_sec=2.0)
    asyncio.run(bucket.acquire())

    assert sleeps == []


def test_second_acquire_sleeps_for_interval(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: clock["t"])
    sleeps = _patch_sleep(monkeypatch)

    bucket = TokenBucket(rate_per_sec=2.0)  # 0.5s interval
    asyncio.run(bucket.acquire())
    asyncio.run(bucket.acquire())

    assert sleeps == [0.5]


def test_acquire_does_not_sleep_if_enough_time_passed(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: clock["t"])
    sleeps = _patch_sleep(monkeypatch)

    bucket = TokenBucket(rate_per_sec=2.0)
    asyncio.run(bucket.acquire())
    clock["t"] = 105.0
    asyncio.run(bucket.acquire())

    assert sleeps == []
