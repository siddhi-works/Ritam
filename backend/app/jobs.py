"""Job bodies, dispatch and progress events. Jobs run through Redis/ARQ when it is configured and
answers, otherwise through the durable Postgres queue in this process (app.queue)."""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from functools import partial
from typing import Any

from arq.connections import ArqRedis
from redis.exceptions import RedisError

from app.audit.pipeline import run_audit
from app.config import Settings
from app.ingest.fetch import make_fetcher
from app.ingest.service import ingest_url
from app.llm import LLMProvider
from app.models import Audit, AuditStatus
from app.packs import load_pack
from app.queue import PgJobStore, Worker
from app.storage import LocalStore

log = logging.getLogger(__name__)


def channel(audit_id: str) -> str:
    return f"audit:{audit_id}:events"


class EventBus:
    """Redis pub/sub when available, otherwise in-memory fan-out (single process)."""

    def __init__(self, redis: ArqRedis | None):
        self._redis = redis
        self._local: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    async def publish(self, audit_id: str, event: str, data: dict[str, Any]) -> None:
        msg = {"event": event, "data": data}
        for q in self._local.get(audit_id, []):
            q.put_nowait(msg)
        if self._redis is not None:
            try:
                await self._redis.publish(channel(audit_id), json.dumps(msg, default=str))
            except RedisError:
                pass

    async def subscribe(self, audit_id: str) -> AsyncIterator[dict[str, Any]]:
        if self._redis is not None:
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(channel(audit_id))
            except (RedisError, OSError):
                pubsub = None
            if pubsub is not None:
                try:
                    async for raw in pubsub.listen():
                        if raw.get("type") == "message":
                            yield json.loads(raw["data"])
                finally:
                    await pubsub.unsubscribe(channel(audit_id))
                    await pubsub.aclose()  # type: ignore[no-untyped-call]
                return
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._local[audit_id].append(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._local[audit_id].remove(q)


class JobContext:
    """Everything a job needs; built once per process (API fallback or ARQ worker)."""

    def __init__(self, settings: Settings, sessionmaker: Any, llm: LLMProvider, bus: EventBus):
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.llm = llm
        self.bus = bus
        self.store = LocalStore(settings.raw_store_dir)
        self.fetcher = make_fetcher(settings.js_fallback)

    async def aclose(self) -> None:
        await self.fetcher.aclose()


async def audit_job(jc: JobContext, audit_id: str) -> str:
    """Run one report. Errors propagate: the queue retries, and only after the last attempt does
    `give_up` mark the report failed (re-running is safe: findings are replaced, reads cached)."""

    async def emit(event: str, data: dict[str, Any]) -> None:
        await jc.bus.publish(audit_id, event, data)

    async with jc.sessionmaker() as session:
        row = await session.get(Audit, uuid.UUID(audit_id))
        pack = load_pack(row.pack if row is not None else "credit_card")
        audit = await run_audit(
            session,
            audit_id=uuid.UUID(audit_id),
            llm=jc.llm,
            fetcher=jc.fetcher,
            store=jc.store,
            settings=jc.settings,
            pack=pack,
            emit=emit,
        )
    return audit.status.value


async def give_up(jc: JobContext, name: str, args: list[str], error: str) -> None:
    """A job failed for the last time. For a report: mark it failed with the reason and tell any
    open progress page, so nobody waits forever."""
    log.error("job gave up", extra={"job": name, "error": error[:300]})
    if name != "audit_job" or not args:
        return
    audit_id = args[0]
    async with jc.sessionmaker() as session:
        row = await session.get(Audit, uuid.UUID(audit_id))
        if row is not None and row.status not in (AuditStatus.COMPLETE, AuditStatus.PARTIAL):
            row.status = AuditStatus.FAILED
            row.stats = {**(row.stats or {}), "error": error[:500]}
            await session.commit()
    await jc.bus.publish(audit_id, "failed", {"error": error[:200]})


async def ingest_job(jc: JobContext, source_id: str) -> str:
    async with jc.sessionmaker() as session:
        source = await ingest_url(session, jc.store, jc.settings, jc.fetcher, uuid.UUID(source_id))
    return source.status.value


JOBS = {"audit_job": audit_job, "ingest_job": ingest_job}


class Dispatcher:
    """ARQ when Redis answers; otherwise the durable Postgres queue in this process."""

    def __init__(self, redis: ArqRedis | None, worker: Worker):
        self._redis = redis
        self.worker = worker

    async def enqueue(self, name: str, *args: str) -> str:
        if self._redis is not None:
            try:
                await self._redis.ping()
                await self._redis.enqueue_job(name, *args)
                return "queue"
            except (RedisError, OSError):
                pass
        await self.worker.enqueue(name, *args)
        return "durable"


def make_worker(jc: JobContext) -> Worker:
    return Worker(
        PgJobStore(jc.sessionmaker),
        {name: partial(fn, jc) for name, fn in JOBS.items()},
        on_give_up=partial(give_up, jc),
    )
