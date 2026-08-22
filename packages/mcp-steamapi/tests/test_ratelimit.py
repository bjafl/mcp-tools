import asyncio

import mcp_steamapi.ratelimit as ratelimit_mod
from mcp_steamapi.ratelimit import TokenBucket


def test_first_acquire_does_not_sleep(monkeypatch):
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: 100.0)
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(ratelimit_mod.asyncio, "sleep", fake_sleep)

    bucket = TokenBucket(rate_per_sec=2.0)
    asyncio.run(bucket.acquire())

    assert sleeps == []


def test_second_acquire_sleeps_for_interval(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: clock["t"])
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(ratelimit_mod.asyncio, "sleep", fake_sleep)

    async def run_two():
        bucket = TokenBucket(rate_per_sec=2.0)  # 0.5s interval
        await bucket.acquire()
        await bucket.acquire()

    asyncio.run(run_two())

    assert sleeps == [0.5]


def test_acquire_does_not_sleep_if_enough_time_passed(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(ratelimit_mod.time, "monotonic", lambda: clock["t"])
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(ratelimit_mod.asyncio, "sleep", fake_sleep)

    async def run_two():
        bucket = TokenBucket(rate_per_sec=2.0)
        await bucket.acquire()
        clock["t"] = 105.0
        await bucket.acquire()

    asyncio.run(run_two())

    assert sleeps == []
