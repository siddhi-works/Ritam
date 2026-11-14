"""POST /api/statements: check a credit card bill; /compare: last month's and this month's. The
files are read in memory, personal details are masked before the AI sees them, and nothing is
stored. The work itself lives in app.bills."""

import asyncio
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import _Limiter, get_session
from app.bills import Bill, BillError, CardTerms, check_bill, check_pair, read_bill
from app.discovery import match_card
from app.models import SourceKind
from app.reports import latest_public_report
from app.statements import TERM_KINDS
from app.terms import in_force, load_terms

TERMS_PDF_KINDS = {SourceKind.MITC_PDF.value, SourceKind.KFS_PDF.value}

router = APIRouter(prefix="/api/statements", tags=["statements"])
Session = Annotated[AsyncSession, Depends(get_session)]
_limiter = _Limiter(limit=10, window_s=3600)


async def card_terms(session: AsyncSession, card_name: str, on: date | None) -> CardTerms | None:
    """The card's terms in force on the bill's date (today when the bill has no date), from the
    bank's own documents across Ritam's public reports."""
    report = await latest_public_report(session, card_name)
    if report is None:
        return None
    by_attr = await load_terms(session, card_name)
    day = on or date.today()
    values: dict[str, list[Decimal]] = {}
    for kind in TERM_KINDS:
        snapshot = in_force(by_attr.get(kind, []), day)
        for v in snapshot.values if snapshot else ():
            amount = (v.norm or {}).get("value")
            if isinstance(amount, int | float):
                values.setdefault(kind, []).append(Decimal(str(amount)))
    read_pdf = any(
        v.source_kind in TERMS_PDF_KINDS for versions in by_attr.values() for v in versions
    )
    listed = frozenset(k for k in TERM_KINDS if by_attr.get(k)) if read_pdf else None
    waiver_now = in_force(by_attr.get("annual_fee_waiver", []), day)
    return CardTerms(
        values=values,
        listed=listed,
        waiver=waiver_now.values[0].value[:200] if waiver_now else None,
        report_id=str(report.id),
    )


async def _read_bill(request: Request, file: UploadFile) -> Bill:
    limit = request.app.state.settings.max_upload_bytes
    try:
        return await read_bill(
            await file.read(limit + 1),
            request.app.state.llm,
            filename=file.filename or "",
            content_type=file.content_type or "",
            max_bytes=limit,
            parse_timeout_s=request.app.state.settings.parse_timeout_s,
        )
    except BillError as exc:
        raise HTTPException(exc.status, exc.message) from exc


async def _check(
    session: AsyncSession, bill: Bill, card: str | None, lifetime_free: bool
) -> dict[str, Any]:
    matched = match_card(card or "") if card else None
    terms = await card_terms(session, matched.name, bill.facts.statement_date) if matched else None
    return check_bill(
        bill, card=matched.name if matched else None, terms=terms, lifetime_free=lifetime_free
    )


LIMIT_MESSAGE = "Too many bills checked from this address; try again in an hour."


@router.post("")
async def check_statement(
    request: Request,
    session: Session,
    file: Annotated[UploadFile, File()],
    card: Annotated[str | None, Form(max_length=200)] = None,
    lifetime_free: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    _limiter.check(request, LIMIT_MESSAGE)
    return await _check(session, await _read_bill(request, file), card, lifetime_free)


@router.post("/compare")
async def compare_statements(
    request: Request,
    session: Session,
    previous: Annotated[UploadFile, File()],
    current: Annotated[UploadFile, File()],
    card: Annotated[str | None, Form(max_length=200)] = None,
    lifetime_free: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    """Last month's bill and this month's: everything the single check finds on the newer bill,
    plus the checks that need both (late fee against the right due date, interest after full
    payment, limit cut, missing reward points)."""
    _limiter.check(request, LIMIT_MESSAGE, cost=2)
    a, b = await asyncio.gather(_read_bill(request, previous), _read_bill(request, current))
    matched = match_card(card or "") if card else None
    newest = max((d for d in (a.facts.statement_date, b.facts.statement_date) if d), default=None)
    terms = await card_terms(session, matched.name, newest) if matched else None
    try:
        return check_pair(
            a, b, card=matched.name if matched else None, terms=terms, lifetime_free=lifetime_free
        )
    except BillError as exc:
        raise HTTPException(exc.status, exc.message) from exc
