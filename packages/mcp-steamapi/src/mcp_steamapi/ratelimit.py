import asyncio
import time


class TokenBucket:
    """Async rate limiter: acquire() awaits until the next slot is available.

    No lock: there is no `await` between reading and writing `self._next`, so a
    single-threaded asyncio event loop cannot interleave two callers mid-update.
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
