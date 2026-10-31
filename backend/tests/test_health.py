from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_reports_degraded_when_dependencies_are_down() -> None:
    # Unroutable ports: the API must still start and answer, reporting each component.
    settings = Settings(
        _env_file=None,  # never read the developer's real .env (it holds API keys)
        env="test",
        database_url="postgresql+asyncpg://u:p@127.0.0.1:1/x",
        redis_url="redis://127.0.0.1:1/0",
        neo4j_password=None,
        gemini_api_key=None,
        dependency_timeout_s=1.0,
    )
    with TestClient(create_app(settings)) as client:
        r = client.get("/health", headers={"x-request-id": "abc"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "abc"
    body = r.json()
    assert body["status"] == "degraded"
    assert body["components"]["db"]["status"] == "down"
    assert body["components"]["redis"]["status"] == "down"
    assert body["components"]["neo4j"]["status"] == "disabled"
    assert body["components"]["llm"]["status"] == "down"


def test_unknown_route_is_problem_json() -> None:
    settings = Settings(_env_file=None, env="test", gemini_api_key=None, neo4j_password=None)
    with TestClient(create_app(settings)) as client:
        r = client.get("/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 404
