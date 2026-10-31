"""Deployment behaviour: liveness without DB, no-Redis mode, internal endpoints."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "env": "test",
        "database_url": "postgresql+asyncpg://u:p@127.0.0.1:1/x",  # unreachable on purpose
        "redis_url": "",
        "neo4j_password": None,
        "gemini_api_key": None,
        "dependency_timeout_s": 1.0,
    }
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def test_livez_answers_even_when_every_dependency_is_down() -> None:
    with TestClient(create_app(settings())) as c:
        r = c.get("/livez")
    assert r.status_code == 200 and r.json() == {"status": "alive"}


def test_empty_redis_url_means_in_process_mode_and_redis_shows_disabled() -> None:
    s = settings()
    assert s.redis_url is None
    with TestClient(create_app(s)) as c:
        assert c.app.state.redis is None  # type: ignore[attr-defined]
        body = c.get("/health").json()
    assert body["components"]["redis"]["status"] == "disabled"


def test_heartbeat_is_hidden_without_token_config_and_rejects_bad_tokens() -> None:
    with TestClient(create_app(settings())) as c:
        assert c.post("/internal/heartbeat").status_code == 404
    with TestClient(create_app(settings(internal_token="s3cret"))) as c:
        assert c.post("/internal/heartbeat").status_code == 401
        assert (
            c.post("/internal/heartbeat", headers={"X-Internal-Token": "nope"}).status_code == 401
        )
        ok = c.post("/internal/heartbeat", headers={"X-Internal-Token": "s3cret"})
    assert ok.status_code == 200 and ok.json()["neo4j"] == "disabled"


def test_cors_regex_allows_vercel_previews_only() -> None:
    s = settings(cors_origin_regex=r"https://ritam[a-z0-9-]*\.vercel\.app")
    with TestClient(create_app(s)) as c:
        good = c.get("/livez", headers={"Origin": "https://ritam-git-main-siddhi.vercel.app"})
        bad = c.get("/livez", headers={"Origin": "https://evil.example"})
    assert (
        good.headers.get("access-control-allow-origin")
        == "https://ritam-git-main-siddhi.vercel.app"
    )
    assert "access-control-allow-origin" not in bad.headers
