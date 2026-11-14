"""POST /api/advisor: what to look for in a credit card, from the person's own spending (Beta)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.advisor import Answers, build
from app.api.deps import _Limiter, get_session
from app.benchmarks import benchmark_texts

router = APIRouter(prefix="/api", tags=["advisor"])
_limiter = _Limiter(limit=120, window_s=3600)
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/advisor")
async def advisor(request: Request, session: Session, answers: Answers) -> dict[str, Any]:
    """The checklist, with dated market benchmarks where Ritam has enough recent data."""
    _limiter.check(request)
    try:
        texts = await benchmark_texts(session)
    except SQLAlchemyError:
        texts = {}  # the checklist works without benchmarks
    return build(answers, texts).as_dict()
