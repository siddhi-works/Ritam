"""Audit pipeline: plan, fetch, extract, analyse, persist, summarise. Each step is timed in
audit.stats["trace"]."""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.checklist import build_checklist
from app.analysis.copydetect import copy_edges, single_origin_findings
from app.analysis.facts import ClaimFact, Finding, SourceFact, SubQuestion
from app.analysis.rules import Analysis
from app.audit import prompts
from app.config import Settings
from app.extract.prompt import scope_key
from app.extract.service import ExtractionStats, extract_source
from app.ingest.fetch import Fetcher
from app.ingest.service import ingest_url
from app.llm import LLMError, LLMProvider
from app.models import (
    Audit,
    AuditSource,
    AuditStatus,
    ChecklistAction,
    ChecklistItem,
    Claim,
    FindingLabel,
    FindingType,
    Source,
    SourcePage,
    SourceStatus,
)
from app.models import Finding as FindingRow
from app.packs import Pack, sync_pack
from app.storage import LocalStore

log = logging.getLogger(__name__)
Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _noop(_: str, __: dict[str, Any]) -> None:
    return None


class Trace:
    def __init__(self, emit: Emit):
        self.steps: list[dict[str, Any]] = []
        self._emit = emit

    async def step(self, name: str, **detail: Any) -> "TraceStep":
        await self._emit("step.started", {"step": name, **detail})
        return TraceStep(self, name, detail)


class TraceStep:
    def __init__(self, trace: Trace, name: str, detail: dict[str, Any]):
        self.trace, self.name, self.detail = trace, name, detail
        self.started = time.monotonic()

    async def done(self, **result: Any) -> None:
        entry = {"step": self.name, **self.detail, **result,
                 "ms": int((time.monotonic() - self.started) * 1000)}  # fmt: skip
        self.trace.steps.append(entry)
        await self.trace._emit("step.done", entry)


async def _retry_db(
    session: AsyncSession,
    op: Callable[[], Awaitable[Any]],
    *,
    refresh: Sequence[Any] = (),
    attempts: int = 3,
) -> Any:
    """Run a DB unit that ends in commit, retrying if the connection drops. Don't wrap LLM calls in
    this."""
    for attempt in range(1, attempts + 1):
        try:
            return await op()
        except (DBAPIError, OSError) as exc:
            transient = isinstance(exc, OSError) or exc.connection_invalidated
            if not transient or attempt == attempts:
                raise
            log.warning("database connection dropped; retrying", extra={"attempt": attempt})
            await asyncio.sleep(attempt)
            await session.rollback()
            for obj in refresh:
                await session.refresh(obj)
    raise RuntimeError("unreachable")


def source_fact(s: Source, pages: list[str]) -> SourceFact:
    observed = s.archived_at or s.fetched_at
    return SourceFact(
        id=str(s.id),
        kind=s.kind.value,
        tier=s.authority_tier,
        title=s.title or s.url or "Untitled",
        url=s.url,
        publisher=s.publisher,
        published_at=s.published_at,
        effective_from=s.effective_from,
        announced_at=s.announced_at,
        date_confidence=s.date_confidence,
        observed_at=observed.date() if observed else None,
        archived=s.archived_at is not None,
        redirected_to=(s.meta or {}).get("redirected_to"),
        said_at=s.said_at,
        pages=tuple(pages),
    )


def claim_fact(c: Claim) -> ClaimFact:
    return ClaimFact(
        id=str(c.id),
        source_id=str(c.source_id),
        attribute=c.attribute_key,
        value_raw=c.value_raw,
        value_norm=c.value_norm,
        quote=c.quote,
        page_no=c.page_no,
        conditions=c.conditions,
        valid_from=c.valid_from,
    )


async def _plan(
    llm: LLMProvider, pack: Pack, question: str
) -> tuple[list[str], list[SubQuestion], str]:
    try:
        result = await llm.generate_structured(
            task="reason", system=prompts.plan_system(pack),
            prompt=prompts.plan_prompt(pack, question), schema=prompts.plan_schema(pack),
        )  # fmt: skip
    except LLMError as exc:
        attrs, subs = prompts.fallback_plan(pack)
        return attrs, subs, f"fallback ({str(exc)[:120]})"
    attrs, subs = prompts.parse_plan(result.data)
    return attrs, subs, f"{result.provider}:{result.model}"


async def _summary(llm: LLMProvider, findings: list[Finding]) -> dict[str, Any]:
    if not findings:
        return prompts.summary_payload(prompts.fallback_summary(findings), source="template")
    prompt = f"Findings JSON:\n{prompts.findings_json(findings)}"
    problems: list[str] = []
    for _ in range(2):  # one retry if validation fails
        try:
            result = await llm.generate_structured(
                task="reason", system=prompts.EXPLAIN_SYSTEM, prompt=prompt, schema=prompts.Summary
            )
        except LLMError:
            break
        text = result.data.summary
        problems = prompts.validate_summary(text, findings)
        if not problems:
            return prompts.summary_payload(text, source=f"{result.provider}:{result.model}")
        prompt += f"\n\nYour previous summary was rejected: {problems}. Fix it."
    return prompts.summary_payload(
        prompts.fallback_summary(findings), source="template", problems=problems
    )


async def run_audit(
    session: AsyncSession,
    *,
    audit_id: uuid.UUID,
    llm: LLMProvider,
    fetcher: Fetcher,
    store: LocalStore,
    settings: Settings,
    pack: Pack,
    emit: Emit = _noop,
    today: date | None = None,
) -> Audit:
    audit = await session.get(Audit, audit_id)
    if audit is None:
        raise ValueError(f"audit {audit_id} not found")
    trace = Trace(emit)
    audit.status = AuditStatus.RUNNING
    await sync_pack(session, pack)
    await session.commit()

    # 1. Plan (AI suggestion; deterministic fallback)
    step = await trace.step("plan")
    question = audit.question + (f" (Product: {audit.product_name})" if audit.product_name else "")
    attrs, subs, planner = await _plan(llm, pack, question)
    audit.plan = {"attributes": attrs, "sub_questions": [{"text": s.text, "attributes": list(s.attributes)} for s in subs],
                  "planner": planner, "label": "ai_suggestion"}  # fmt: skip
    await _retry_db(session, session.commit, refresh=[audit])
    await step.done(planner=planner, sub_questions=len(subs))

    # 2. Ingest pending URL sources
    source_ids = list(
        await session.scalars(select(AuditSource.source_id).where(AuditSource.audit_id == audit_id))
    )
    sources = list(await session.scalars(select(Source).where(Source.id.in_(source_ids))))
    for s in sources:
        if s.status == SourceStatus.PENDING and s.url:
            step = await trace.step("fetch", source_id=str(s.id), url=s.url)
            await ingest_url(session, store, settings, fetcher, s.id)
            await session.refresh(s)
            await step.done(status=s.status.value, method=s.fetch_method, error=s.error)

    # 3. Extract claims from every parsed source
    for s in sources:
        if s.status not in (SourceStatus.PARSED, SourceStatus.EXTRACTED):
            continue
        step = await trace.step("extract", source_id=str(s.id), title=s.title)
        try:

            async def extract_one(src: Source = s) -> ExtractionStats:
                result = await extract_source(session, llm, pack, src, product=audit.product_name)
                src.status = SourceStatus.EXTRACTED
                await session.commit()
                return result

            # Retried on dropped connections; LLM output is cached per chunk, so a retry is free.
            stats = await _retry_db(session, extract_one, refresh=[audit, *sources])
            await step.done(**{k: v for k, v in stats.as_dict().items() if k != "llm_attempts"})
        except Exception as exc:  # noqa: BLE001 - one source must not fail the audit
            source_id = str(s.id)
            await session.rollback()
            # A rollback expires every loaded object; touching one afterwards would trigger a lazy
            # load outside the async context (MissingGreenlet). Reload what we keep using.
            await session.refresh(audit)
            for other in sources:
                await session.refresh(other)
            log.exception("extraction failed", extra={"source_id": source_id})
            await step.done(error=f"{type(exc).__name__}: {str(exc)[:200]}")

    # 4. Analyse (reads only; retried if the connection drops)
    step = await trace.step("analyse")
    usable = [s for s in sources if s.status == SourceStatus.EXTRACTED]

    async def load_facts() -> tuple[list[SourceFact], list[ClaimFact]]:
        pages_by_source: dict[uuid.UUID, list[str]] = {}
        for p in await session.scalars(
            select(SourcePage)
            .where(SourcePage.source_id.in_([s.id for s in usable]))
            .order_by(SourcePage.page_no)
        ):
            pages_by_source.setdefault(p.source_id, []).append(p.text)
        facts = [source_fact(s, pages_by_source.get(s.id, [])) for s in usable]
        claims = [claim_fact(c) for c in await session.scalars(
            select(Claim).where(
                Claim.source_id.in_([s.id for s in usable]),
                Claim.verified.is_(True),
                Claim.prompt_version == scope_key(audit.product_name, pack.prompt_version),
            )
        )]  # fmt: skip
        await session.commit()  # end the read transaction; don't hold a connection
        return facts, claims

    facts, claims = await _retry_db(session, load_facts, refresh=[audit, *sources])
    analysis = Analysis(
        pack, facts, claims, sub_questions=subs, today=today, product=audit.product_name
    )
    findings = analysis.run()
    edges = copy_edges(facts)
    findings += single_origin_findings(facts, analysis.comparable_claims, edges)
    checklist = build_checklist(
        findings,
        {f.id: f for f in facts},
        labels={a.key: a.label for a in pack.attributes},
        pack=pack,
    )
    await step.done(findings=len(findings), copy_edges=len(edges), checklist=len(checklist))

    # 5. Persist findings + checklist (re-runs replace earlier results), committed before the
    # summary's LLM call so a slow or failed summary can't lose them.
    async def persist() -> None:
        await session.execute(delete(ChecklistItem).where(ChecklistItem.audit_id == audit_id))
        await session.execute(delete(FindingRow).where(FindingRow.audit_id == audit_id))
        key_to_id: dict[str, uuid.UUID] = {}
        for f in findings:
            row = FindingRow(
                id=uuid.uuid4(), audit_id=audit_id, type=FindingType(f.type), subtype=f.subtype,
                severity=f.severity, confidence=f.confidence, label=FindingLabel(f.label), title=f.title,
                detail={**f.detail, "key": f.key, "attribute": f.attribute},
                claim_ids=[uuid.UUID(c) for c in f.claim_ids], source_ids=[uuid.UUID(s) for s in f.source_ids],
                rule_id=f.rule_id,
            )  # fmt: skip
            key_to_id[f.key] = row.id
            session.add(row)
        session.add_all(
            ChecklistItem(
                audit_id=audit_id,
                rank=c.rank,
                text=c.text,
                why=c.why,
                verify_url=c.verify_url,
                finding_ids=[key_to_id[k] for k in c.finding_keys if k in key_to_id],
                action=ChecklistAction(c.action),
            )  # fmt: skip
            for c in checklist
        )
        await session.commit()

    await _retry_db(session, persist, refresh=[audit, *sources])

    # 6. Summary (AI wording, validated against the findings; template fallback)
    step = await trace.step("summary")
    failed = [s for s in sources if s.status == SourceStatus.FAILED]
    summary = await _summary(llm, findings)
    await step.done(generated_by=summary["generated_by"])

    async def finish() -> None:
        audit.summary = summary
        audit.stats = {
            "sources_total": len(sources),
            "sources_analysed": len(usable),
            "sources_failed": len(failed),
            "claims_verified": len(claims),
            "findings": len(findings),
            "copy_edges": [e.__dict__ for e in edges],
            "trace": trace.steps,
        }
        audit.status = (
            AuditStatus.PARTIAL if failed or len(usable) < len(sources) else AuditStatus.COMPLETE
        )
        audit.finished_at = datetime.now(UTC)
        await session.commit()

    await _retry_db(session, finish, refresh=[audit])
    await emit("complete", {"status": audit.status.value, "findings": len(findings)})
    return audit
