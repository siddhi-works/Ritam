"""ARQ worker. Run with: arq app.worker.WorkerSettings

Job bodies live in app.jobs and are shared with the API's in-process fallback (local dev
without Redis), so both paths run identical code.
"""

import logging
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app import jobs
from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.llm import make_router
from app.llm.budget import SqlBudget
from app.observability import configure_logging

log = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx["engine"] = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(ctx["engine"])
    llm = make_router(settings)
    llm.budget = SqlBudget(sessionmaker, settings.llm_daily_budget)
    ctx["jc"] = jobs.JobContext(
        settings,
        sessionmaker,
        llm,
        jobs.EventBus(ctx["redis"]),
    )
    log.info("worker started")


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["jc"].llm.aclose()
    await ctx["jc"].aclose()
    await ctx["engine"].dispose()


async def audit_job(ctx: dict[str, Any], audit_id: str) -> str:
    return await jobs.audit_job(ctx["jc"], audit_id)


async def ingest_job(ctx: dict[str, Any], source_id: str) -> str:
    return await jobs.ingest_job(ctx["jc"], source_id)


async def ping(ctx: dict[str, Any]) -> str:
    """Smoke-test job: proves API → Redis → worker wiring."""
    return "pong"


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping, audit_job, ingest_job]
    on_startup = startup
    on_shutdown = shutdown
    # The ARQ worker only exists when Redis is configured (docker-compose / scale-out).
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379/0")
    max_jobs = 4
    job_timeout = 900
    keep_result = 3600
