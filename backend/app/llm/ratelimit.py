import asyncio
import time


class TokenBucket:
    """Async token bucket, per process."""

    def __init__(self, rate: int, per: float = 60.0) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self._capacity = float(rate)
        self._tokens = float(rate)
        self._refill_per_s = rate / per
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._refill_per_s
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self._refill_per_s)
