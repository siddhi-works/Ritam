import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from arq.connections import ArqRedis
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import ConnectionPool
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from app import jobs
from app.api import audits, discover, health, internal, sources
from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.errors import install_error_handlers
from app.graph import make_driver
from app.llm import make_router
from app.llm.budget import SqlBudget
from app.models import Audit, AuditStatus
from app.observability import configure_logging, request_id_var
from app.storage import LocalStore

log = logging.getLogger(__name__)


async def recover_interrupted_audits(app: FastAPI) -> int:
    """In-process mode (no Redis): a restart kills any running audit job, so mark those audits
    failed instead of leaving the UI waiting forever. With Redis, ARQ owns job recovery."""
    try:
        async with app.state.sessionmaker() as session:
            result = await session.execute(
                update(Audit)
                .where(Audit.status.in_([AuditStatus.QUEUED, AuditStatus.RUNNING]))
                .values(
                    status=AuditStatus.FAILED,
                    stats=Audit.stats.op("||")(
                        {"error": "Interrupted by a server restart. Please run the audit again."}
                    ),
                )
            )
            await session.commit()
            count = result.rowcount or 0
    except (SQLAlchemyError, OSError) as exc:  # the API must start even if the DB is down
        log.warning("audit recovery skipped", extra={"error": type(exc).__name__})
        return 0
    if count:
        log.warning("marked interrupted audits as failed", extra={"count": count})
    return count


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        app.state.settings = settings
        app.state.engine = make_engine(settings.database_url)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        # No REDIS_URL (e.g. Render free tier): jobs run in-process. Otherwise a lazy pool, so the
        # API starts (degraded) even if Redis is not up yet.
        app.state.redis = (
            ArqRedis(
                connection_pool=ConnectionPool.from_url(
                    settings.redis_url, socket_connect_timeout=settings.dependency_timeout_s
                )
            )
            if settings.redis_url
            else None
        )
        app.state.neo4j = make_driver(settings)
        app.state.llm = make_router(settings)
        app.state.budget = SqlBudget(app.state.sessionmaker, settings.llm_daily_budget)
        app.state.llm.budget = app.state.budget
        app.state.store = LocalStore(settings.raw_store_dir)
        app.state.bus = jobs.EventBus(app.state.redis)
        app.state.job_context = jobs.JobContext(
            settings, app.state.sessionmaker, app.state.llm, app.state.bus
        )
        app.state.dispatcher = jobs.Dispatcher(app.state.redis, app.state.job_context)
        if app.state.redis is None:
            await recover_interrupted_audits(app)
        log.info(
            "api started",
            extra={"env": settings.env, "queue": "redis" if app.state.redis else "in_process"},
        )
        try:
            yield
        finally:
            await app.state.llm.aclose()
            await app.state.job_context.aclose()
            if app.state.neo4j:
                await app.state.neo4j.close()
            if app.state.redis is not None:
                await app.state.redis.aclose()
            await app.state.engine.dispose()

    app = FastAPI(title="Ritam API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid[:64])
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["x-request-id"] = rid[:64]
        return response

    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(sources.router)
    app.include_router(audits.router)
    app.include_router(internal.router)
    app.include_router(discover.router)
    return app


app = create_app()
