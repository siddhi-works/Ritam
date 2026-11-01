import json
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_session
from app.api.sources import SourceOut
from app.extract.prompt import scope_key
from app.ingest.netguard import BlockedURL, check_url
from app.ingest.service import AUTHORITY_TIER, IngestError, IngestInput, ingest
from app.models import (
    Audit,
    AuditSource,
    AuditStatus,
    ChecklistItem,
    Claim,
    Finding,
    Source,
    SourceKind,
    SourceStatus,
)
from app.packs import load_pack

router = APIRouter(prefix="/api/audits", tags=["audits"])
TERMINAL = {AuditStatus.COMPLETE, AuditStatus.PARTIAL, AuditStatus.FAILED}
Session = Annotated[AsyncSession, Depends(get_session)]
MAX_SOURCES = 12


class UrlIn(BaseModel):
    type: Literal["url"]
    url: HttpUrl
    kind: SourceKind = SourceKind.OFFICIAL_PAGE
    title: str | None = Field(default=None, max_length=300)  # e.g. from source discovery


class TextIn(BaseModel):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=200_000)
    kind: Literal[SourceKind.USER_CHAT, SourceKind.USER_UPLOAD] = SourceKind.USER_UPLOAD
    title: str | None = Field(default=None, max_length=500)
    said_at: date | None = None


class ExistingIn(BaseModel):
    type: Literal["source"]
    id: uuid.UUID


class AuditIn(BaseModel):
    question: str = Field(min_length=5, max_length=1000)
    product: str | None = Field(default=None, max_length=200)
    pack: Literal["credit_card"] = "credit_card"
    sources: list[Annotated[UrlIn | TextIn | ExistingIn, Field(discriminator="type")]] = Field(
        min_length=1, max_length=MAX_SOURCES
    )


class AuditCreated(BaseModel):
    audit_id: uuid.UUID
    status: AuditStatus
    runner: str


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


_limiter = _Limiter(limit=10, window_s=3600)


@router.post("", response_model=AuditCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_audit(request: Request, session: Session, payload: AuditIn) -> AuditCreated:
    client = request.client.host if request.client else "unknown"
    if not _limiter.allow(client):
        raise HTTPException(429, "Too many audits from this address; try again in an hour.")
    settings = request.app.state.settings
    budget = getattr(request.app.state, "budget", None)
    if budget is not None and await budget.live_audits_paused(settings.llm_reserve_fraction):
        raise HTTPException(
            503,
            "Live analysis is paused for today: the free AI quota is nearly used up (it resets at "
            "midnight US Pacific time, 12:30-13:30 IST). The preloaded demo audits still work.",
        )
    audit = Audit(
        id=uuid.uuid4(),
        question=payload.question.strip(),
        product_name=(payload.product or "").strip() or None,
        pack=payload.pack,
        status=AuditStatus.QUEUED,
        stats={},
    )
    session.add(audit)
    # Links are added only after every source row is flushed: the models have no ORM
    # relationship, so SQLAlchemy may otherwise insert audit_source before source (FK error).
    linked: list[uuid.UUID] = []
    for item in payload.sources:
        if isinstance(item, UrlIn):
            try:
                url = await check_url(str(item.url))
            except BlockedURL as exc:
                raise HTTPException(400, f"{item.url}: {exc}") from exc
            source = Source(id=uuid.uuid4(), kind=item.kind, url=url, authority_tier=AUTHORITY_TIER[item.kind],
                            title=(item.title or "").strip() or None, status=SourceStatus.PENDING, meta={})  # fmt: skip
            session.add(source)
        elif isinstance(item, TextIn):
            inp = IngestInput(body=item.text.encode("utf-8"), kind=item.kind, title=item.title,
                              content_type="text/plain", said_at=item.said_at)  # fmt: skip
            try:
                source, _ = await ingest(session, request.app.state.store, settings, inp)
            except IngestError as exc:
                raise HTTPException(422, str(exc)) from exc
        else:
            found = await session.get(Source, item.id)
            if found is None:
                raise HTTPException(404, f"source {item.id} not found")
            source = found
        if source.id not in linked:
            linked.append(source.id)
    await session.flush()
    session.add_all(AuditSource(audit_id=audit.id, source_id=sid) for sid in linked)
    await session.commit()
    runner = await request.app.state.dispatcher.enqueue("audit_job", str(audit.id))
    return AuditCreated(audit_id=audit.id, status=audit.status, runner=runner)


class FindingOut(BaseModel):
    id: uuid.UUID
    key: str | None
    type: str
    subtype: str | None
    label: str
    severity: int
    confidence: float
    title: str
    rule_id: str
    attribute: str | None
    detail: dict[str, Any]
    claim_ids: list[uuid.UUID]
    source_ids: list[uuid.UUID]


class ChecklistOut(BaseModel):
    rank: int
    text: str
    why: str
    action: str
    verify_url: str | None
    finding_ids: list[uuid.UUID]


class Cell(BaseModel):
    claim_id: uuid.UUID
    value: str
    quote: str
    page_no: int | None
    conditions: str | None
    valid_from: date | None


class MatrixRow(BaseModel):
    attribute: str
    label: str
    mitc_required: bool
    cells: dict[str, list[Cell]]  # source_id → claims


class Coverage(BaseModel):
    """Per attribute: official, third_party, conflict or missing."""

    total: int
    official: int
    third_party: int
    conflict: int
    missing: int
    by_attribute: dict[str, str]


class AuditOut(BaseModel):
    id: uuid.UUID
    product_name: str | None
    pack: str
    question: str
    status: AuditStatus
    created_at: datetime
    finished_at: datetime | None
    plan: dict[str, Any] | None
    summary: dict[str, Any] | None
    stats: dict[str, Any]
    sources: list[SourceOut]
    matrix: list[MatrixRow]
    coverage: Coverage
    findings: list[FindingOut]
    checklist: list[ChecklistOut]


class Highlight(BaseModel):
    audit_id: uuid.UUID
    finding: FindingOut
    told: dict[str, Any]
    terms: dict[str, Any]


DEMO_CACHE = "public, max-age=300, stale-while-revalidate=86400"


@router.get("/highlight", response_model=Highlight | None)
async def highlight(session: Session, response: Response) -> Highlight | None:
    """One demo finding for the home page."""
    rows = await session.execute(
        select(Finding)
        .join(Audit, Audit.id == Finding.audit_id)
        .where(Audit.is_demo.is_(True), Finding.type.in_(["chat_mismatch", "conflict"]))
        .order_by(Finding.type.desc(), Finding.severity.desc())  # chat_mismatch first
        .limit(10)
    )
    for f in rows.scalars():
        d = f.detail
        told = d.get("told") or (d.get("evidence") or [None])[0]
        terms = (d.get("terms_valid_then") or [None])[0] or (d.get("evidence") or [None, None])[1]
        if told and terms:
            response.headers["Cache-Control"] = DEMO_CACHE
            return Highlight(audit_id=f.audit_id, finding=_finding_out(f), told=told, terms=terms)
    return None


def _finding_out(f: Finding) -> FindingOut:
    return FindingOut(
        id=f.id, key=f.detail.get("key"), type=f.type.value, subtype=f.subtype, label=f.label.value,
        severity=f.severity, confidence=f.confidence, title=f.title, rule_id=f.rule_id,
        attribute=f.detail.get("attribute"), detail=f.detail, claim_ids=f.claim_ids, source_ids=f.source_ids,
    )  # fmt: skip


@router.get("/{audit_id}", response_model=AuditOut)
async def get_audit(session: Session, audit_id: uuid.UUID, response: Response) -> AuditOut:
    audit = await session.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(404, "audit not found")
    if audit.is_demo and audit.status in TERMINAL:
        response.headers["Cache-Control"] = DEMO_CACHE  # demo audits don't change between seeds
    pack = load_pack(audit.pack)
    source_ids = list(
        await session.scalars(select(AuditSource.source_id).where(AuditSource.audit_id == audit_id))
    )
    sources = list(
        await session.scalars(
            select(Source).where(Source.id.in_(source_ids)).order_by(Source.authority_tier)
        )
    )
    claims = list(await session.scalars(
        select(Claim).where(
            Claim.source_id.in_(source_ids),
            Claim.verified.is_(True),
            Claim.prompt_version == scope_key(audit.product_name, pack.prompt_version),
        )
    ))  # fmt: skip
    findings = list(await session.scalars(
        select(Finding).where(Finding.audit_id == audit_id).order_by(Finding.severity.desc())
    ))  # fmt: skip
    checklist = list(await session.scalars(
        select(ChecklistItem).where(ChecklistItem.audit_id == audit_id).order_by(ChecklistItem.rank)
    ))  # fmt: skip

    wanted = list((audit.plan or {}).get("attributes", []))
    for c in claims:
        if c.attribute_key not in wanted:
            wanted.append(c.attribute_key)
    rows = []
    for key in wanted:
        spec = pack.get(key)
        if spec is None:
            continue
        cells: dict[str, list[Cell]] = defaultdict(list)
        for c in claims:
            if c.attribute_key == key:
                cells[str(c.source_id)].append(Cell(claim_id=c.id, value=c.value_raw, quote=c.quote,
                    page_no=c.page_no, conditions=c.conditions, valid_from=c.valid_from))  # fmt: skip
        rows.append(
            MatrixRow(
                attribute=key, label=spec.label, mitc_required=spec.mitc_required, cells=dict(cells)
            )
        )

    issuer_ids = {
        str(s.id) for s in sources if s.authority_tier == 1 and s.kind != SourceKind.USER_CHAT
    }
    conflicted = {str(f.detail.get("attribute")) for f in findings if f.type.value == "conflict"}
    by_attr: dict[str, str] = {}
    for row in rows:
        if row.attribute in conflicted:
            by_attr[row.attribute] = "conflict"
        elif any(sid in issuer_ids for sid in row.cells):
            by_attr[row.attribute] = "official"
        elif row.cells:
            by_attr[row.attribute] = "third_party"
        else:
            by_attr[row.attribute] = "missing"
    counts = {
        k: list(by_attr.values()).count(k)
        for k in ("official", "third_party", "conflict", "missing")
    }
    coverage = Coverage(total=len(by_attr), by_attribute=by_attr, **counts)

    return AuditOut(
        id=audit.id, question=audit.question, product_name=audit.product_name, pack=audit.pack, coverage=coverage,
        status=audit.status, created_at=audit.created_at,
        finished_at=audit.finished_at, plan=audit.plan, summary=audit.summary, stats=audit.stats or {},
        sources=[SourceOut.of(s) for s in sources], matrix=rows,
        findings=[_finding_out(f) for f in findings],
        checklist=[ChecklistOut(rank=c.rank, text=c.text, why=c.why, action=c.action.value,
                                verify_url=c.verify_url, finding_ids=c.finding_ids) for c in checklist],
    )  # fmt: skip


class AuditListItem(BaseModel):
    id: uuid.UUID
    question: str
    status: AuditStatus
    is_demo: bool
    created_at: datetime
    findings: int | None


@router.get("", response_model=list[AuditListItem])
async def list_audits(
    session: Session, demo_only: bool = False, limit: int = 20
) -> list[AuditListItem]:
    q = select(Audit).order_by(Audit.is_demo.desc(), Audit.created_at.desc()).limit(min(limit, 50))
    if demo_only:
        q = q.where(Audit.is_demo.is_(True))
    return [
        AuditListItem(
            id=a.id,
            question=a.question,
            status=a.status,
            is_demo=a.is_demo,
            created_at=a.created_at,
            findings=(a.stats or {}).get("findings"),
        )  # fmt: skip
        for a in await session.scalars(q)
    ]


@router.get("/{audit_id}/events")
async def audit_events(
    request: Request, session: Session, audit_id: uuid.UUID
) -> EventSourceResponse:
    """SSE stream of audit progress. Sends the current state first so a reconnect can't miss
    completion."""
    audit = await session.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(404, "audit not found")
    snapshot = {"status": audit.status.value, "trace": (audit.stats or {}).get("trace", [])}
    done = audit.status in TERMINAL
    bus = request.app.state.bus

    async def stream() -> AsyncIterator[dict[str, str]]:
        yield {"event": "snapshot", "data": json.dumps(snapshot, default=str)}
        if done:
            return
        async for msg in bus.subscribe(str(audit_id)):
            if await request.is_disconnected():
                break
            yield {"event": msg["event"], "data": json.dumps(msg["data"], default=str)}
            if msg["event"] in ("complete", "failed"):
                break

    return EventSourceResponse(stream(), ping=15, send_timeout=30)
