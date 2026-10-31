import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.ingest.netguard import BlockedURL, check_url
from app.ingest.service import AUTHORITY_TIER, IngestError, IngestInput, ingest
from app.models import Claim, Source, SourceKind, SourcePage, SourceStatus

router = APIRouter(prefix="/api", tags=["sources"])
Session = Annotated[AsyncSession, Depends(get_session)]

UPLOAD_KINDS = {k for k in SourceKind if k != SourceKind.USER_CHAT}


class SourceOut(BaseModel):
    id: uuid.UUID
    kind: SourceKind
    status: SourceStatus
    title: str | None
    url: str | None
    publisher: str | None
    authority_tier: int
    doc_type: str | None
    page_count: int | None
    content_hash: str | None
    fetch_method: str | None
    fetched_at: datetime | None
    archived_at: datetime | None
    published_at: date | None
    effective_from: date | None
    announced_at: date | None
    said_at: date | None
    date_method: str | None
    date_confidence: float | None
    undated: bool = Field(description="No date found, or date confidence below 0.5")
    error: str | None
    meta: dict[str, Any]
    reused: bool = False

    @classmethod
    def of(cls, s: Source, reused: bool = False) -> "SourceOut":
        dated = s.date_confidence is not None and s.date_confidence >= 0.5
        return cls(
            id=s.id,
            kind=s.kind,
            status=s.status,
            title=s.title,
            url=s.url,
            publisher=s.publisher,
            authority_tier=s.authority_tier,
            doc_type=s.doc_type,
            page_count=s.page_count,
            content_hash=s.content_hash,
            fetch_method=s.fetch_method,
            fetched_at=s.fetched_at,
            archived_at=s.archived_at,
            published_at=s.published_at,
            effective_from=s.effective_from,
            announced_at=s.announced_at,
            said_at=s.said_at,
            date_method=s.date_method,
            date_confidence=s.date_confidence,
            undated=s.status == SourceStatus.PARSED and not dated,
            error=s.error,
            meta=s.meta or {},
            reused=reused,
        )


class UrlSourceIn(BaseModel):
    url: HttpUrl
    kind: SourceKind = SourceKind.OFFICIAL_PAGE
    title: str | None = Field(default=None, max_length=500)


class TextSourceIn(BaseModel):
    kind: Literal[SourceKind.USER_CHAT, SourceKind.USER_UPLOAD] = SourceKind.USER_UPLOAD
    title: str | None = Field(default=None, max_length=500)
    text: str = Field(min_length=1)
    said_at: date | None = None


class Highlight(BaseModel):
    claim_id: uuid.UUID
    page_no: int
    char_start: int  # offset within the page text
    char_end: int


class PageOut(BaseModel):
    page_no: int
    text: str


class SourceView(BaseModel):
    source: SourceOut
    pages: list[PageOut]
    highlights: list[Highlight]


def _ingest_error(exc: IngestError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.post("/uploads", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def upload(
    request: Request,
    session: Session,
    file: Annotated[UploadFile, File()],
    kind: Annotated[SourceKind, Form()] = SourceKind.USER_UPLOAD,
    title: Annotated[str | None, Form(max_length=500)] = None,
) -> SourceOut:
    """Upload a PDF, saved HTML page (Ctrl+S) or text file."""
    settings = request.app.state.settings
    if kind not in UPLOAD_KINDS:
        raise HTTPException(422, "use POST /api/sources/text for customer-care chats")
    body = await file.read(settings.max_upload_bytes + 1)
    if len(body) > settings.max_upload_bytes:
        raise HTTPException(413, f"file exceeds {settings.max_upload_bytes // (1024 * 1024)} MB")
    if not body:
        raise HTTPException(422, "file is empty")
    inp = IngestInput(
        body=body,
        kind=kind,
        title=title,
        filename=file.filename or "",
        content_type=file.content_type or "",
    )
    try:
        source, reused = await ingest(session, request.app.state.store, settings, inp)
    except IngestError as exc:
        raise _ingest_error(exc) from exc
    await session.commit()
    return SourceOut.of(source, reused)


@router.post("/sources/text", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def add_text(request: Request, session: Session, payload: TextSourceIn) -> SourceOut:
    """Paste text, or a customer-care chat (personal identifiers are masked before storage)."""
    settings = request.app.state.settings
    if len(payload.text) > settings.max_text_chars:
        raise HTTPException(413, f"text exceeds {settings.max_text_chars} characters")
    inp = IngestInput(
        body=payload.text.encode("utf-8"),
        kind=payload.kind,
        title=payload.title,
        content_type="text/plain",
        said_at=payload.said_at,
    )
    try:
        source, reused = await ingest(session, request.app.state.store, settings, inp)
    except IngestError as exc:
        raise _ingest_error(exc) from exc
    await session.commit()
    return SourceOut.of(source, reused)


@router.post("/sources/url", response_model=SourceOut, status_code=status.HTTP_202_ACCEPTED)
async def add_url(request: Request, session: Session, payload: UrlSourceIn) -> SourceOut:
    """Queue a URL for fetching (httpx → headless browser → Wayback). Poll GET /api/sources/{id}."""
    try:
        url = await check_url(str(payload.url))
    except BlockedURL as exc:
        raise HTTPException(400, str(exc)) from exc
    source = Source(
        id=uuid.uuid4(),
        kind=payload.kind,
        url=url,
        title=payload.title,
        authority_tier=AUTHORITY_TIER[payload.kind],
        status=SourceStatus.PENDING,
        meta={},
    )
    session.add(source)
    await session.commit()
    await request.app.state.dispatcher.enqueue("ingest_job", str(source.id))
    return SourceOut.of(source)


@router.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(session: Session, source_id: uuid.UUID) -> SourceOut:
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "source not found")
    return SourceOut.of(source)


@router.get("/sources/{source_id}/view", response_model=SourceView)
async def view_source(
    session: Session, source_id: uuid.UUID, claim: uuid.UUID | None = None
) -> SourceView:
    """Source text page by page, with verified claim quotes highlighted (all, or one claim)."""
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "source not found")
    pages = (
        await session.scalars(
            select(SourcePage).where(SourcePage.source_id == source_id).order_by(SourcePage.page_no)
        )
    ).all()
    q = select(Claim).where(Claim.source_id == source_id, Claim.verified.is_(True))
    if claim is not None:
        q = q.where(Claim.id == claim)
    claims = (await session.scalars(q)).all()
    if claim is not None and not claims:
        raise HTTPException(404, "claim not found in this source")
    highlights = [
        Highlight(claim_id=c.id, page_no=c.page_no, char_start=c.char_start, char_end=c.char_end)
        for c in claims
        if c.page_no is not None and c.char_start is not None and c.char_end is not None
    ]
    return SourceView(
        source=SourceOut.of(source),
        pages=[PageOut(page_no=p.page_no, text=p.text) for p in pages],
        highlights=highlights,
    )
