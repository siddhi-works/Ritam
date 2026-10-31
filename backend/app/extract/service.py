"""Claim extraction: the LLM proposes claims; code checks every quote and number before keeping one."""

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.extract.normalize import normalize_value
from app.extract.numbers import numbers_supported
from app.extract.prompt import (
    PROMPT_VERSION,
    build_prompt,
    chunk_pages,
    claim_dicts,
    output_schema,
    scope_key,
    system_prompt,
)
from app.extract.quotecheck import QuoteLocator
from app.ingest.dates import find_dates
from app.ingest.parse import Page
from app.llm import LLMError, LLMProvider
from app.models import Claim, ExtractionCache, Source, SourcePage
from app.packs import Pack

log = logging.getLogger(__name__)
MAX_CLAIMS_PER_CHUNK = 80  # cap for models that over-extract


class ExtractionCacheBackend(Protocol):
    async def get(
        self, content_hash: str, chunk_index: int
    ) -> tuple[str, list[dict[str, Any]]] | None: ...

    async def put(
        self, content_hash: str, chunk_index: int, model: str, claims: list[dict[str, Any]]
    ) -> None: ...


@dataclass
class CheckedClaim:
    attribute: str
    value_raw: str
    value_norm: dict[str, Any] | None
    conditions: str | None
    quote: str  # for verified claims: the exact source text at the matched span
    model_quote: str
    valid_from: date | None
    extractor: str
    verified: bool
    drop_reason: str | None = None
    page_no: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    match_score: float | None = None
    match_method: str | None = None


@dataclass
class ExtractionStats:
    chunks: int = 0
    cached_chunks: int = 0
    failed_chunks: int = 0
    proposed: int = 0
    verified: int = 0
    duplicates: int = 0
    dropped: Counter[str] = field(default_factory=Counter)
    models: Counter[str] = field(default_factory=Counter)
    llm_attempts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scope: str = PROMPT_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunks": self.chunks,
            "cached_chunks": self.cached_chunks,
            "failed_chunks": self.failed_chunks,
            "proposed": self.proposed,
            "verified": self.verified,
            "duplicates": self.duplicates,
            "dropped": dict(self.dropped),
            "models": dict(self.models),
            "llm_attempts": self.llm_attempts[-50:],
            "errors": self.errors,
            "prompt_version": self.scope,
        }


def _value_supported(value_raw: str, quote: str, value_type: str) -> bool:
    """Every number in the value must appear in the quote. A date may be written differently in
    the two ("30.09.2026" vs "September 30, 2026"), so dates are compared as dates."""
    if value_type == "date":
        value_dates = {c.value for c in find_dates(value_raw)}
        if value_dates:
            return value_dates <= {c.value for c in find_dates(quote)}
    return numbers_supported(value_raw, quote)


def check_claim(
    raw: dict[str, Any], locator: QuoteLocator, pack: Pack, extractor: str
) -> CheckedClaim:
    spec = pack.get(raw["attribute"])
    value_raw = str(raw.get("value_raw", "")).strip()
    model_quote = str(raw.get("quote", "")).strip()
    valid_from = raw.get("valid_from")
    claim = CheckedClaim(
        attribute=raw["attribute"],
        value_raw=value_raw,
        value_norm=None,
        conditions=(raw.get("conditions") or None),
        quote=model_quote,
        model_quote=model_quote,
        valid_from=date.fromisoformat(valid_from) if isinstance(valid_from, str) else valid_from,
        extractor=extractor,
        verified=False,
    )
    if spec is None:
        claim.drop_reason = "unknown_attribute"
        return claim
    match = locator.locate(model_quote)
    if match is None:
        claim.drop_reason = "quote_not_found"
        return claim
    page_text = locator.page_text(match.page_no)
    source_span = page_text[match.char_start : match.char_end]
    if not _value_supported(value_raw, source_span, spec.value_type):
        claim.drop_reason = "numbers_not_in_quote"
        return claim
    claim.verified = True
    claim.quote = source_span
    claim.page_no, claim.char_start, claim.char_end = (
        match.page_no,
        match.char_start,
        match.char_end,
    )
    claim.match_score, claim.match_method = match.score, match.method
    claim.value_norm = normalize_value(value_raw, spec.value_type)
    return claim


def _is_duplicate(c: CheckedClaim, kept: list[CheckedClaim]) -> bool:
    for k in kept:
        if k.attribute != c.attribute or k.page_no != c.page_no or k.value_norm != c.value_norm:
            continue
        assert k.char_start is not None and k.char_end is not None
        assert c.char_start is not None and c.char_end is not None
        overlap = min(k.char_end, c.char_end) - max(k.char_start, c.char_start)
        if overlap > 0.5 * min(k.char_end - k.char_start, c.char_end - c.char_start):
            return True
    return False


async def extract_document(
    llm: LLMProvider,
    pack: Pack,
    pages: list[Page],
    *,
    content_hash: str,
    title: str | None,
    kind: str,
    cache: ExtractionCacheBackend | None = None,
    product: str | None = None,
) -> tuple[list[CheckedClaim], ExtractionStats]:
    stats = ExtractionStats(scope=scope_key(product, pack.prompt_version))
    locator = QuoteLocator(pages)
    schema = output_schema(pack)
    checked: list[CheckedClaim] = []

    for index, chunk in enumerate(chunk_pages(pages)):
        stats.chunks += 1
        cached = await cache.get(content_hash, index) if cache else None
        if cached is not None:
            extractor, raws = cached
            stats.cached_chunks += 1
        else:
            try:
                result = await llm.generate_structured(
                    task="extract",
                    system=system_prompt(pack),
                    prompt=build_prompt(pack, chunk, title=title, kind=kind, product=product),
                    schema=schema,
                )
            except LLMError as exc:
                stats.failed_chunks += 1
                stats.errors.append(f"chunk {index}: {str(exc)[:300]}")
                continue
            extractor = f"{result.provider}:{result.model}"
            raws = claim_dicts(result.data)
            stats.llm_attempts.extend(result.attempts)
            if cache:
                await cache.put(content_hash, index, extractor, raws)

        if len(raws) > MAX_CLAIMS_PER_CHUNK:
            stats.dropped["over_extraction_cap"] += len(raws) - MAX_CLAIMS_PER_CHUNK
            raws = raws[:MAX_CLAIMS_PER_CHUNK]
        stats.models[extractor] += len(raws)
        stats.proposed += len(raws)
        checked.extend(check_claim(r, locator, pack, extractor) for r in raws)

    kept: list[CheckedClaim] = []
    for c in checked:
        if not c.verified:
            stats.dropped[c.drop_reason or "unknown"] += 1
            kept.append(c)
        elif _is_duplicate(c, [k for k in kept if k.verified]):
            stats.duplicates += 1
        else:
            stats.verified += 1
            kept.append(c)
    return kept, stats


class SqlExtractionCache:
    def __init__(self, session: AsyncSession, scope: str = PROMPT_VERSION):
        self._session = session
        self._scope = scope

    async def get(
        self, content_hash: str, chunk_index: int
    ) -> tuple[str, list[dict[str, Any]]] | None:
        row = await self._session.scalar(
            select(ExtractionCache)
            .where(
                ExtractionCache.content_hash == content_hash,
                ExtractionCache.chunk_index == chunk_index,
                ExtractionCache.prompt_version == self._scope,
            )
            .order_by(ExtractionCache.created_at.desc())
            .limit(1)
        )
        result = (row.model, row.output["claims"]) if row else None
        await self._session.commit()  # don't hold a connection open during the LLM call
        return result

    async def put(
        self, content_hash: str, chunk_index: int, model: str, claims: list[dict[str, Any]]
    ) -> None:
        self._session.add(
            ExtractionCache(
                content_hash=content_hash,
                chunk_index=chunk_index,
                prompt_version=self._scope,
                model=model,
                output={"claims": claims},
            )
        )
        # Commit now so a later failure doesn't waste the LLM call.
        await self._session.commit()


async def extract_source(
    session: AsyncSession,
    llm: LLMProvider,
    pack: Pack,
    source: Source,
    product: str | None = None,
) -> ExtractionStats:
    """Extract, verify and store claims for one parsed source (replacing earlier claims)."""
    rows = (
        await session.scalars(
            select(SourcePage).where(SourcePage.source_id == source.id).order_by(SourcePage.page_no)
        )
    ).all()
    pages = [Page(page_no=r.page_no, text=r.text, char_start=r.char_start) for r in rows]
    if not pages or not source.content_hash:
        raise ValueError(f"source {source.id} has no parsed pages")

    claims, stats = await extract_document(
        llm,
        pack,
        pages,
        content_hash=source.content_hash,
        title=source.title,
        kind=source.kind.value,
        cache=SqlExtractionCache(session, scope_key(product, pack.prompt_version)),
        product=product,
    )
    observed: datetime | None = source.archived_at or source.fetched_at
    scope = scope_key(product, pack.prompt_version)
    await session.execute(
        delete(Claim).where(Claim.source_id == source.id, Claim.prompt_version == scope)
    )
    session.add_all(
        Claim(
            source_id=source.id,
            product_id=source.product_id,
            attribute_key=c.attribute,
            value_raw=c.value_raw[:1000],
            value_norm=c.value_norm,
            conditions=c.conditions,
            quote=c.quote[:2000],
            page_no=c.page_no,
            char_start=c.char_start,
            char_end=c.char_end,
            match_score=c.match_score,
            verified=c.verified,
            drop_reason=c.drop_reason,
            valid_from=c.valid_from or (source.effective_from if c.verified else None),
            observed_at=observed,
            said_at=source.said_at,
            extractor=c.extractor[:64],
            prompt_version=scope,
        )
        for c in claims
        if c.attribute in pack.keys  # unknown attributes have no FK target; counted in stats
    )
    source.meta = {**(source.meta or {}), "extraction": stats.as_dict()}
    await session.flush()
    return stats
