from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.discovery import CatalogueCard, catalogue, match_card
from app.models import Audit
from app.packs import load_pack
from app.reports import latest_public_reports
from app.terms import changes_between, load_terms, then_vs_now

router = APIRouter(prefix="/api/cards", tags=["cards"])
Session = Annotated[AsyncSession, Depends(get_session)]


class CardOut(BaseModel):
    id: str
    name: str
    bank: str
    report_id: str | None
    checked_at: datetime | None
    findings: int | None


def _out(card: CatalogueCard, report: Audit | None) -> CardOut:
    return CardOut(
        id=card.id,
        name=card.name,
        bank=card.bank,
        report_id=str(report.id) if report else None,
        checked_at=report.finished_at if report else None,
        findings=(report.stats or {}).get("findings") if report else None,
    )


@router.get("", response_model=list[CardOut])
async def list_cards(
    session: Session, q: Annotated[str | None, Query(max_length=200)] = None
) -> list[CardOut]:
    """Cards on the checked list, each with its latest public report. With `q`, only the card that
    the text names (empty list when none matches)."""
    if q:
        card = match_card(q)
        cards = [card] if card else []
    else:
        cards = [c for c in catalogue() if c.pack == "credit_card"]
    reports = await latest_public_reports(session, [c.name for c in cards]) if cards else {}
    return [_out(c, reports.get(c.name)) for c in cards]


@router.get("/{card_id}/terms")
async def card_terms_over_time(
    session: Session,
    card_id: str,
    since: Annotated[date | None, Query(description="e.g. the day you got the card")] = None,
) -> dict[str, Any]:
    """Terms in force on `since` and today, and every dated change in between, from the bank's own
    documents in Ritam's checked reports. No AI calls."""
    card = next((c for c in catalogue() if c.id == card_id), None)
    if card is None:
        raise HTTPException(404, "Ritam doesn't have this card on its list.")
    today = date.today()
    then = since or today
    if then > today:
        raise HTTPException(422, "The date can't be in the future.")
    by_attr = await load_terms(session, card.name)
    labels = {a.key: a.label for a in load_pack(card.pack).attributes}
    dated = sorted(v.dated for vs in by_attr.values() for v in vs if v.dated)
    return {
        "card": card.name,
        "since": then.isoformat(),
        "today": today.isoformat(),
        "terms": [
            {**row, "label": labels.get(row["attribute"], row["attribute"])}
            for row in then_vs_now(by_attr, then, today)
        ],
        "changes": [c.as_dict() for c in changes_between(by_attr, then, today)],
        "coverage": {
            "values": sum(len(v) for v in by_attr.values()),
            "earliest": dated[0].isoformat() if dated else None,
            "latest": dated[-1].isoformat() if dated else None,
            "note": "Built from the bank documents Ritam has read. A change Ritam never saw a "
            "document for won't appear here.",
        },
    }
