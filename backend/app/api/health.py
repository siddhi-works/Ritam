import asyncio
import time
from collections.abc import Awaitable
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter(tags=["health"])

Status = Literal["ok", "down", "disabled"]


class ComponentHealth(BaseModel):
    status: Status
    latency_ms: int | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    components: dict[str, ComponentHealth]


async def _probe(check: Awaitable[Any] | None, limit_s: float) -> ComponentHealth:
    if check is None:
        return ComponentHealth(status="disabled")
    started = time.monotonic()
    try:
        await asyncio.wait_for(check, limit_s)
    except Exception as exc:  # noqa: BLE001 - health must report, never raise
        return ComponentHealth(status="down", detail=type(exc).__name__)
    return ComponentHealth(status="ok", latency_ms=int((time.monotonic() - started) * 1000))


async def _db_check(request: Request) -> None:
    async with request.app.state.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


@router.get("/livez")
async def livez() -> dict[str, str]:
    """Liveness only. No database, so the keep-awake ping doesn't wake Neon."""
    return {"status": "alive"}


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Readiness of Postgres, LLM keys and optional Redis/Neo4j. The LLM itself isn't called."""
    state = request.app.state
    timeout = state.settings.dependency_timeout_s
    neo4j = state.neo4j
    db, redis, graph = await asyncio.gather(
        _probe(_db_check(request), timeout),
        _probe(state.redis.ping() if state.redis is not None else None, timeout),
        _probe(neo4j.verify_connectivity() if neo4j else None, timeout),
    )
    providers = state.llm.configured_providers()
    llm = ComponentHealth(
        status="ok" if state.llm.is_configured() else "down",
        detail=", ".join(providers) if providers else "no LLM API key configured",
    )
    components = {"db": db, "redis": redis, "neo4j": graph, "llm": llm}
    core_ok = db.status == "ok" and redis.status != "down" and llm.status == "ok"
    return HealthResponse(status="ok" if core_ok else "degraded", components=components)
