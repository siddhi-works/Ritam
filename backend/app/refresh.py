"""Keeping card data fresh: queue a report for every card on the checked list, from its official
sources only (no web search, so no search credits). Documents that haven't changed cost no AI
calls (the extraction cache), so a monthly refresh mostly catches the documents that did change.
Called by a scheduled workflow through /internal/refresh-cards."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery import catalogue
from app.ingest.netguard import check_url
from app.ingest.service import AUTHORITY_TIER
from app.models import Audit, AuditSource, AuditStatus, Source, SourceKind, SourceStatus
from app.reports import latest_public_reports

QUESTION = "Tell me everything important about this card"


def url_source(url: str, kind: SourceKind, title: str | None) -> Source:
    """A source row waiting to be fetched (the URL must already have passed check_url)."""
    return Source(
        id=uuid.uuid4(),
        kind=kind,
        url=url,
        authority_tier=AUTHORITY_TIER[kind],
        title=(title or "").strip() or None,
        status=SourceStatus.PENDING,
        meta={},
    )


async def queue_card_reports(
    session: AsyncSession, *, only_missing: bool
) -> list[tuple[str, uuid.UUID]]:
    """Create a queued report per catalogue card; returns (card name, report id) to enqueue."""
    cards = [c for c in catalogue() if c.pack == "credit_card"]
    if only_missing:
        have = await latest_public_reports(session, [c.name for c in cards])
        cards = [c for c in cards if c.name not in have]
    created: list[tuple[str, uuid.UUID]] = []
    for card in cards:
        sources = []
        for s in card.sources:
            try:
                url = await check_url(s["url"])
            except ValueError:
                continue  # a catalogue link that no longer passes the network guard is skipped
            sources.append(url_source(url, SourceKind(s["kind"]), s.get("title")))
        if not sources:
            continue  # no report without sources: it would wait forever
        audit = Audit(
            id=uuid.uuid4(),
            question=QUESTION,
            product_name=card.name,
            pack=card.pack,
            status=AuditStatus.QUEUED,
            stats={"refresh": True},
        )
        session.add(audit)
        session.add_all(sources)
        await session.flush()
        session.add_all(AuditSource(audit_id=audit.id, source_id=src.id) for src in sources)
        created.append((card.name, audit.id))
    await session.commit()
    return created
