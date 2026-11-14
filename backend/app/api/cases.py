"""Case file endpoints: a complaint letter, the RBI escalation dates, the card-closure penalty and
calendar reminders. No AI and nothing stored."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import _Limiter, get_session
from app.cases import (
    REASONS,
    REFS,
    LetterItem,
    closure_letter,
    closure_penalty,
    complaint_letter,
    complaint_timeline,
    reminders_ics,
)
from app.discovery import CatalogueCard, classify, match_card
from app.discovery.domains import host
from app.models import AuditSource, Claim, Source
from app.reports import latest_public_report

router = APIRouter(prefix="/api/cases", tags=["cases"])
Session = Annotated[AsyncSession, Depends(get_session)]
_limiter = _Limiter(limit=120, window_s=3600)


class Item(BaseModel):
    rule: str = Field(max_length=64)
    charge: str | None = Field(default=None, max_length=200)
    amount: Decimal | None = Field(default=None, ge=0, le=10_000_000)
    ref: str | None = Field(default=None, max_length=200)


class LetterIn(BaseModel):
    findings: list[Item] = Field(min_length=1, max_length=20)
    card: str | None = Field(default=None, max_length=200)
    statement_date: date | None = None
    complained_on: date | None = None
    replied_on: date | None = None
    note: str | None = Field(default=None, max_length=1000)


async def grievance_contact(session: AsyncSession, card: CatalogueCard) -> dict[str, Any] | None:
    """The bank's own words on where to complain: from the card's latest checked report, else
    from any checked document on the same bank's official site (contacts are bank-wide)."""
    report = await latest_public_report(session, card.name)
    base = (
        select(Claim.value_raw, Claim.quote, Source.url, Source.title)
        .join(Source, Source.id == Claim.source_id)
        .where(
            Claim.verified.is_(True),
            Claim.attribute_key == "grievance_redressal",
            # Banks list separate officers for digital loans; card complaints go elsewhere.
            ~Claim.value_raw.ilike("%digital lending%"),
            ~Claim.quote.ilike("%digital lending%"),
        )
        .order_by(Source.authority_tier)
        .limit(1)
    )
    row = None
    if report is not None:
        row = (
            await session.execute(
                base.join(AuditSource, AuditSource.source_id == Claim.source_id).where(
                    AuditSource.audit_id == report.id
                )
            )
        ).first()
    hosts = {host(s["url"]) for s in card.sources if classify(s["url"])[1]}
    if row is None and hosts:
        row = (
            await session.execute(
                base.where(
                    or_(
                        *(Source.url.ilike(f"%://{h}/%") for h in hosts),
                        *(Source.url.ilike(f"%://www.{h}/%") for h in hosts),
                    )
                )
            )
        ).first()
    if row is None:
        return None
    return {
        "text": row.value_raw,
        "quote": row.quote,
        "url": row.url,
        "source": row.title,
        "report_id": str(report.id) if report else None,
    }


def _timeline(complained_on: date | None, replied_on: date | None) -> list[dict[str, str]]:
    if complained_on is None:
        return []
    return [
        {"date": s.when.isoformat(), "what": s.what, "why": s.why}
        for s in complaint_timeline(complained_on, replied_on)
    ]


@router.post("/letter")
async def letter(request: Request, session: Session, payload: LetterIn) -> dict[str, Any]:
    """A complaint letter from bill-checker findings, where to send it, and the escalation dates."""
    _limiter.check(request)
    items = [
        LetterItem(i.rule, i.charge, i.amount, REFS.get(i.rule))
        for i in payload.findings
        if i.rule in REASONS
    ]
    if not items:
        raise HTTPException(422, "None of these findings is something to raise with the bank.")
    card = match_card(payload.card) if payload.card else None
    contact = await grievance_contact(session, card) if card else None
    origin = request.headers.get("origin") or ""
    report_link = (
        f"{origin}/audit/{contact['report_id']}"
        if contact and contact["report_id"] and origin.startswith("https://")
        else None
    )
    text = complaint_letter(
        items,
        card=card.name if card else payload.card,
        bank=card.bank if card else None,
        statement_date=payload.statement_date,
        report_link=report_link,
        extra=payload.note,
    )
    return {
        "letter": text,
        "bank": card.bank if card else None,
        "where_to_send": contact,
        "timeline": _timeline(payload.complained_on, payload.replied_on),
    }


class ClosureIn(BaseModel):
    requested_on: date
    closed_on: date | None = None
    card: str | None = Field(default=None, max_length=200)


@router.post("/closure")
async def closure(request: Request, payload: ClosureIn) -> dict[str, Any]:
    """Penalty owed for a card not closed within 7 working days, with a letter claiming it."""
    _limiter.check(request)
    today = date.today()
    if payload.requested_on > today or (
        payload.closed_on and payload.closed_on < payload.requested_on
    ):
        raise HTTPException(
            422,
            "Check the dates: the request can't be in the future, and the card can't close before it.",
        )
    p = closure_penalty(payload.requested_on, payload.closed_on, today)
    card = match_card(payload.card) if payload.card else None
    text = (
        closure_letter(
            p, card=card.name if card else payload.card, bank=card.bank if card else None
        )
        if p.days_late
        else None
    )
    return {
        **p.as_dict(),
        "letter": text,
        "note": "Applies only if nothing was owed on the card when you asked. Bank holidays aren't "
        "counted here, so the due date may be a day or two later.",
    }


@router.get("/timeline")
async def timeline(
    request: Request, complained_on: date, replied_on: date | None = None
) -> list[dict[str, str]]:
    """The bank-reply and RBI Ombudsman dates for a complaint sent on `complained_on`."""
    _limiter.check(request)
    if complained_on > date.today():
        raise HTTPException(422, "The complaint date can't be in the future.")
    return _timeline(complained_on, replied_on)


@router.get("/reminders.ics")
async def reminders(
    request: Request,
    complained_on: date,
    replied_on: date | None = None,
    title: Annotated[str, Query(max_length=80)] = "Card complaint",
) -> Response:
    """Calendar file with the bank-reply and RBI dates."""
    _limiter.check(request)
    steps = [s for s in complaint_timeline(complained_on, replied_on) if s.when >= date.today()]
    if not steps:
        raise HTTPException(422, "All the dates for this complaint have already passed.")
    body = reminders_ics(steps, title=title, uid_seed=f"{complained_on:%Y%m%d}")
    return Response(
        body,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="ritam-complaint-dates.ics"'},
    )
