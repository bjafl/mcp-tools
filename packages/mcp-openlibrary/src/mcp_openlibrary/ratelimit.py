import asyncio
import time


class TokenBucket:
    """Simple rate limiter: await acquire() until the next slot is available.

    Intended for asyncio callers only. No lock is needed: the read and write of
    ``self._next`` happen with no ``await`` between them, so they are atomic with
    respect to other tasks on the same event loop. Not safe across OS threads.
    """

    def __init__(self, rate_per_sec: float):
        self._interval = 1.0 / rate_per_sec
        self._next = 0.0

    async def acquire(self) -> None:
        now = time.monotonic()
        wait = max(0.0, self._next - now)
        self._next = max(now, self._next) + self._interval
        if wait:
            await asyncio.sleep(wait)
