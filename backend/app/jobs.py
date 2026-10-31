"""Job dispatch and progress events, through Redis/ARQ or in-process when Redis isn't configured."""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from arq.connections import ArqRedis
from redis.exceptions import RedisError

from app.audit.pipeline import run_audit
from app.config import Settings
from app.ingest.fetch import make_fetcher
from app.ingest.service import ingest_url
from app.llm import LLMProvider
from app.packs import load_pack
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
    async def emit(event: str, data: dict[str, Any]) -> None:
        await jc.bus.publish(audit_id, event, data)

    async with jc.sessionmaker() as session:
        try:
            from app.models import Audit

            row = await session.get(Audit, uuid.UUID(audit_id))
            pack = load_pack(row.pack if row is not None else "credit_card")
            audit = await run_audit(
                session, audit_id=uuid.UUID(audit_id), llm=jc.llm, fetcher=jc.fetcher,
                store=jc.store, settings=jc.settings, pack=pack, emit=emit,
            )  # fmt: skip
        except Exception as exc:
            log.exception("audit failed", extra={"audit_id": audit_id})
            await emit("failed", {"error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            from app.models import Audit, AuditStatus

            await session.rollback()
            row = await session.get(Audit, uuid.UUID(audit_id))
            if row is not None:
                row.status = AuditStatus.FAILED
                row.stats = {**(row.stats or {}), "error": str(exc)[:500]}
                await session.commit()
            raise
    return audit.status.value


async def ingest_job(jc: JobContext, source_id: str) -> str:
    async with jc.sessionmaker() as session:
        source = await ingest_url(session, jc.store, jc.settings, jc.fetcher, uuid.UUID(source_id))
    return source.status.value


JOBS = {"audit_job": audit_job, "ingest_job": ingest_job}


class Dispatcher:
    """Enqueue to ARQ if Redis answers; otherwise run in-process (local dev)."""

    def __init__(self, redis: ArqRedis | None, jc: JobContext):
        self._redis = redis
        self._jc = jc
        self._tasks: set[asyncio.Task[Any]] = set()

    async def enqueue(self, name: str, *args: str) -> str:
        if self._redis is None:
            return self._run_in_process(name, *args)
        try:
            await self._redis.ping()
            await self._redis.enqueue_job(name, *args)
            return "queue"
        except (RedisError, OSError):
            return self._run_in_process(name, *args)

    def _run_in_process(self, name: str, *args: str) -> str:
        task = asyncio.create_task(JOBS[name](self._jc, *args))
        self._tasks.add(task)  # keep a reference so the task isn't garbage-collected
        task.add_done_callback(self._tasks.discard)
        return "in_process"
