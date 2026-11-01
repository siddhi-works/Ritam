from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.audits import _Limiter
from app.discovery import SearchBudgetExhausted, TavilySearch, discover
from app.llm.budget import SqlBudget

router = APIRouter(prefix="/api", tags=["discovery"])

_limiter = _Limiter(limit=20, window_s=3600)


class DiscoverIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    product: str | None = Field(default=None, max_length=200)
    pack: Literal["credit_card"] = "credit_card"


class _BudgetedSearch(TavilySearch):
    """Tavily search that stops at the daily cap kept in llm_usage."""

    def __init__(self, api_key: str, budget: SqlBudget | None):
        super().__init__(api_key)
        self._budget = budget

    async def search(self, query: str, **kw: Any) -> list[dict[str, Any]]:
        if self._budget is not None:
            if not await self._budget.allow("tavily"):
                raise SearchBudgetExhausted
            await self._budget.record("tavily")
        return await super().search(query, **kw)


@router.post("/discover")
async def discover_sources(request: Request, payload: DiscoverIn) -> dict[str, Any]:
    """Candidate sources for a card or topic; the user confirms them before the audit."""
    client = request.client.host if request.client else "unknown"
    if not _limiter.allow(client):
        raise HTTPException(429, "Too many searches from this address; try again in an hour.")
    settings = request.app.state.settings
    key = settings.tavily_api_key.get_secret_value() if settings.tavily_api_key else ""
    sm = getattr(request.app.state, "sessionmaker", None)
    budget = SqlBudget(sm, {"tavily": settings.search_daily_budget}) if sm is not None else None
    search = _BudgetedSearch(key, budget) if key else None
    try:
        return await discover(
            question=payload.question.strip(),
            product=(payload.product or "").strip() or None,
            pack=payload.pack,
            search=search,
        )
    finally:
        if search is not None:
            await search.aclose()
