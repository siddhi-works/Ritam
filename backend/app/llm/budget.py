"""Daily call budget per LLM provider, counted in Postgres per Pacific-time day (when Gemini quotas
reset)."""

import logging
from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import LlmUsage

log = logging.getLogger(__name__)
PACIFIC = ZoneInfo("America/Los_Angeles")


def quota_day(now: datetime | None = None) -> date:
    return (now or datetime.now(PACIFIC)).astimezone(PACIFIC).date()


class BudgetGuard(Protocol):
    async def allow(self, provider: str) -> bool: ...

    async def record(self, provider: str) -> None: ...


class SqlBudget:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], budgets: Mapping[str, int]):
        self._sm = sessionmaker
        self._budgets = dict(budgets)

    async def used(self, day: date | None = None) -> dict[str, int]:
        day = day or quota_day()
        try:
            async with self._sm() as s:
                rows = await s.execute(
                    select(LlmUsage.provider, LlmUsage.calls).where(LlmUsage.day == day)
                )
                return {p: c for p, c in rows.all()}
        except (SQLAlchemyError, OSError):
            return {}

    async def allow(self, provider: str) -> bool:
        budget = self._budgets.get(provider)
        if budget is None:
            return True
        return (await self.used()).get(provider, 0) < budget

    async def record(self, provider: str) -> None:
        try:
            async with self._sm() as s:
                stmt = insert(LlmUsage).values(day=quota_day(), provider=provider, calls=1)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[LlmUsage.day, LlmUsage.provider],
                    set_={"calls": LlmUsage.calls + 1, "updated_at": func.now()},
                )
                await s.execute(stmt)
                await s.commit()
        except (SQLAlchemyError, OSError) as exc:
            log.warning("llm budget not recorded", extra={"error": type(exc).__name__})

    async def live_audits_paused(self, reserve_fraction: float) -> bool:
        """True when every provider has used all but `reserve_fraction` of its budget."""
        if not self._budgets:
            return False
        used = await self.used()
        return all(used.get(p, 0) >= b * (1 - reserve_fraction) for p, b in self._budgets.items())
