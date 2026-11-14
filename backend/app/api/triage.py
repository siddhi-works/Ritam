"""POST /api/triage: what went wrong -> which Ritam tool, what it needs, and the first steps."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.deps import _Limiter
from app.triage import route

router = APIRouter(prefix="/api", tags=["triage"])
_limiter = _Limiter(limit=60, window_s=3600)


class TriageIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


@router.post("/triage")
async def triage(request: Request, payload: TriageIn) -> dict[str, Any]:
    """Keyword rules first; the AI is asked only when they find nothing (masked text, fixed list)."""
    _limiter.check(request)
    return (await route(payload.text, getattr(request.app.state, "llm", None))).as_dict()
