import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


class _Limiter:
    """Sliding-window rate limit per client IP."""

    def __init__(self, limit: int, window_s: float):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now, q = time.monotonic(), self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def check(
        self,
        request: Request,
        message: str = "Too many requests from this address; try again in an hour.",
        cost: int = 1,
    ) -> None:
        """Raise 429 when this client is over the limit. `cost` counts one request as several."""
        client = request.client.host if request.client else "unknown"
        if not all(self.allow(client) for _ in range(cost)):
            raise HTTPException(429, message)
