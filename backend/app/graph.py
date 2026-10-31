"""Neo4j read projection. Optional: every caller must tolerate `driver is None` or a failed ping."""

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import Settings


def make_driver(settings: Settings) -> AsyncDriver | None:
    if not settings.neo4j_uri or settings.neo4j_password is None:
        return None
    return AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
        connection_timeout=settings.dependency_timeout_s,
    )
