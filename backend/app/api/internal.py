"""Endpoints for scheduled jobs (GitHub Actions), protected by a shared token."""

import hmac
import logging
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter(prefix="/internal", tags=["internal"])
log = logging.getLogger(__name__)

HEARTBEAT_CYPHER = "MERGE (h:Heartbeat {id: 'ritam'}) SET h.at = $at RETURN h.at AS at"


def _authorise(request: Request, token: str | None) -> None:
    expected = request.app.state.settings.internal_token
    if expected is None or not expected.get_secret_value():
        raise HTTPException(404, "not found")  # disabled: don't reveal the endpoint exists
    if not token or not hmac.compare_digest(token, expected.get_secret_value()):
        raise HTTPException(401, "invalid token")


@router.post("/heartbeat")
async def heartbeat(
    request: Request, x_internal_token: Annotated[str | None, Header()] = None
) -> dict[str, str]:
    """Daily write so Neo4j Aura Free doesn't pause (it pauses after 3 days without writes)."""
    _authorise(request, x_internal_token)
    settings = request.app.state.settings
    at = datetime.now(UTC).isoformat()
    driver = request.app.state.neo4j
    if driver is not None:
        try:
            async with driver.session() as session:
                await (await session.run(HEARTBEAT_CYPHER, at=at)).consume()
            return {"neo4j": "written", "via": "bolt", "at": at}
        except Exception as exc:  # noqa: BLE001 - fall through to the HTTPS route
            log.warning("heartbeat over bolt failed", extra={"error": type(exc).__name__})
    if settings.neo4j_query_api_url and settings.neo4j_password is not None:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                settings.neo4j_query_api_url,
                auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
                json={"statement": HEARTBEAT_CYPHER, "parameters": {"at": at}},
            )
        if resp.status_code in (200, 202):
            return {"neo4j": "written", "via": "https", "at": at}
        raise HTTPException(502, f"Neo4j query API returned {resp.status_code}")
    if driver is None:
        return {"neo4j": "disabled", "at": at}
    raise HTTPException(502, "Neo4j heartbeat failed")
