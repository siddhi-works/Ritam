"""Ingest = store raw bytes → parse into pages → extract dates → persist Source + SourcePages."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ingest.dates import extract_dates
from app.ingest.fetch import Fetcher, FetchFailed, FetchResult
from app.ingest.netguard import BlockedURL
from app.ingest.parse import ParsedDoc, ParseError, parse, parse_pdf, sniff
from app.ingest.redact import redact
from app.models import Source, SourceKind, SourcePage, SourceStatus
from app.storage import LocalStore, sha256

log = logging.getLogger(__name__)

# 1 = issuer or regulator (bank page, MITC, KFS, notice, RBI); 4 = hearsay.
AUTHORITY_TIER: dict[SourceKind, int] = {
    SourceKind.OFFICIAL_PAGE: 1,
    SourceKind.MITC_PDF: 1,
    SourceKind.KFS_PDF: 1,
    SourceKind.BANK_NOTICE: 1,
    SourceKind.RBI_RULE: 1,
    SourceKind.NEWS: 3,
    SourceKind.AGGREGATOR: 3,
    SourceKind.USER_UPLOAD: 3,
    SourceKind.FORUM: 4,
    SourceKind.USER_CHAT: 4,
}


class IngestError(Exception):
    """User-facing ingest failure (bad file, too large, no text)."""


@dataclass
class IngestInput:
    body: bytes
    kind: SourceKind
    title: str | None = None
    url: str | None = None
    filename: str = ""
    content_type: str = ""
    said_at: date | None = None
    fetch: FetchResult | None = None


async def _parse(inp: IngestInput, settings: Settings) -> ParsedDoc:
    def run() -> ParsedDoc:
        kind = sniff(inp.body, inp.content_type, inp.filename)
        if kind == "pdf":
            return parse_pdf(inp.body, max_pages=settings.max_pdf_pages)
        return parse(inp.body, content_type=inp.content_type, filename=inp.filename, url=inp.url)

    # A thread can't be killed on timeout; a process pool is the hardening step if hostile
    # PDFs become a concern. The size and page caps bound the work meanwhile.
    try:
        return await asyncio.wait_for(asyncio.to_thread(run), settings.parse_timeout_s)
    except TimeoutError as exc:
        raise IngestError("parsing took too long; try a smaller file") from exc
    except ParseError as exc:
        raise IngestError(str(exc)) from exc


async def find_duplicate(session: AsyncSession, digest: str, kind: SourceKind) -> Source | None:
    return await session.scalar(
        select(Source)
        .where(
            Source.content_hash == digest,
            Source.kind == kind,
            Source.status == SourceStatus.PARSED,
        )
        .limit(1)
    )


async def populate(
    session: AsyncSession,
    store: LocalStore,
    settings: Settings,
    source: Source,
    inp: IngestInput,
) -> Source:
    """Parse `inp` into `source` (new or pending). Raises IngestError on unusable content."""
    if len(inp.body) > settings.max_upload_bytes:
        raise IngestError(f"file exceeds {settings.max_upload_bytes // (1024 * 1024)} MB")

    meta: dict[str, Any] = dict(source.meta or {})
    body = inp.body
    if inp.kind == SourceKind.USER_CHAT:
        text, counts = redact(body.decode("utf-8", "replace"))
        body = text.encode("utf-8")
        meta["redactions"] = counts

    digest, raw_path = await store.put(body)
    doc = await _parse(replace(inp, body=body), settings)
    today = (
        inp.fetch.archived_at if inp.fetch and inp.fetch.archived_at else datetime.now(UTC)
    ).date()
    dates = extract_dates(doc.text, html=doc.html, pdf_dates=doc.pdf_dates, today=today)

    meta.update({"dates": dates.to_meta(), "warnings": doc.warnings})
    if inp.fetch is not None:
        if inp.url and (warning := redirect_warning(inp.url, inp.fetch.final_url)):
            meta["warnings"] = [warning, *meta["warnings"]]
            meta["redirected_to"] = inp.fetch.final_url
        meta["fetch"] = {
            "final_url": inp.fetch.final_url,
            "content_type": inp.fetch.content_type,
            "attempts": inp.fetch.attempts,
        }

    source.kind = inp.kind
    source.url = inp.url or source.url
    source.title = (inp.title or doc.title or inp.filename or source.url or "Untitled")[:500]
    source.publisher = source.publisher or _publisher(source.url)
    source.authority_tier = AUTHORITY_TIER[inp.kind]
    source.content_hash = digest
    source.raw_path = raw_path
    source.doc_type = doc.doc_type
    source.page_count = len(doc.pages)
    source.fetched_at = inp.fetch.fetched_at if inp.fetch else datetime.now(UTC)
    source.fetch_method = inp.fetch.method if inp.fetch else "upload"
    source.archived_at = inp.fetch.archived_at if inp.fetch else None
    source.published_at = dates.published_at
    source.effective_from = dates.effective_from
    source.announced_at = dates.announced_at
    source.date_method = dates.method
    source.date_confidence = dates.confidence
    source.said_at = inp.said_at
    source.status = SourceStatus.PARSED
    source.error = None
    source.meta = meta

    session.add(source)
    await session.flush()  # assigns source.id for a new row
    await session.execute(delete(SourcePage).where(SourcePage.source_id == source.id))
    session.add_all(
        SourcePage(source_id=source.id, page_no=p.page_no, text=p.text, char_start=p.char_start)
        for p in doc.pages
    )
    await session.flush()
    return source


async def ingest(
    session: AsyncSession, store: LocalStore, settings: Settings, inp: IngestInput
) -> tuple[Source, bool]:
    """Create a parsed Source. Identical content of the same kind is reused."""
    if inp.kind != SourceKind.USER_CHAT:  # chats are redacted first, so their hash differs
        if dup := await find_duplicate(session, sha256(inp.body), inp.kind):
            return dup, True
    source = await populate(session, store, settings, Source(id=uuid.uuid4(), meta={}), inp)
    return source, False


async def ingest_url(
    session: AsyncSession,
    store: LocalStore,
    settings: Settings,
    fetcher: Fetcher,
    source_id: uuid.UUID,
) -> Source:
    """Fetch and parse a pending URL source. Failures are stored on the source, not raised."""
    source = await session.get(Source, source_id)
    if source is None or not source.url:
        raise ValueError(f"source {source_id} not found or has no URL")
    try:
        fetched = await fetcher.fetch(source.url)
        inp = _input_from(source, fetched)
        if fetcher.has_browser and fetched.method == "httpx" and "html" in fetched.content_type:
            inp = await _prefer_rendered(inp, source, fetcher, settings)
        await populate(session, store, settings, source, inp)
    except (FetchFailed, BlockedURL, IngestError) as exc:
        source.status = SourceStatus.FAILED
        source.error = str(exc)
        attempts = getattr(exc, "attempts", None)
        source.meta = {**(source.meta or {}), "fetch": {"attempts": attempts or []}}
        log.warning("source ingest failed", extra={"source_id": str(source_id), "error": str(exc)})
    await session.commit()
    return source


THIN_TEXT_CHARS = 1500


def _input_from(source: Source, fetched: FetchResult) -> IngestInput:
    return IngestInput(
        body=fetched.body,
        kind=source.kind,
        title=source.title,
        url=source.url,
        content_type=fetched.content_type,
        fetch=fetched,
    )


async def _prefer_rendered(
    inp: IngestInput, source: Source, fetcher: Fetcher, settings: Settings
) -> IngestInput:
    """If plain HTTP returned a JavaScript shell, render the page and keep whichever version has
    more text."""
    try:
        plain = await _parse(inp, settings)
    except IngestError:
        plain = None
    if plain is not None and len(plain.text) >= THIN_TEXT_CHARS:
        return inp
    assert inp.fetch is not None and source.url is not None
    try:
        rendered = await fetcher.fetch_with_browser(source.url)
        alt = _input_from(source, rendered)
        alt_doc = await _parse(alt, settings)
    except Exception as exc:  # noqa: BLE001 - keep the plain version if rendering fails
        log.info("browser re-fetch failed", extra={"url": source.url, "error": str(exc)[:200]})
        return inp
    if plain is not None and len(alt_doc.text) <= len(plain.text):
        return inp
    rendered.attempts = [*inp.fetch.attempts, {"method": "httpx", "note": "thin JS shell"}]
    rendered.attempts.append({"method": "browser", "status": rendered.status})
    return alt


def redirect_warning(requested: str, final: str) -> str | None:
    """Warn when a redirect lands on a different page, not just a new domain."""

    def slug(url: str) -> str:
        last = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].lower()
        return last.removesuffix(".html").removesuffix(".page").removesuffix(".aspx")

    old, new = slug(requested), slug(final)
    if old and old != new:
        return (
            f"The requested URL redirected to a different page ({final}). "
            "Check that this is still the product you meant; links to the old page may be stale."
        )
    return None


def _publisher(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.") or None
