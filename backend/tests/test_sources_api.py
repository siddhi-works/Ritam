"""API + database integration tests. They need a real Postgres:

    docker compose up -d postgres
    set RITAM_TEST_DATABASE_URL=postgresql+asyncpg://ritam:ritam@localhost:5432/ritam_test

and are skipped otherwise.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from app.config import Settings
from app.db import normalize_database_url  # noqa: E402
from app.main import create_app

_raw = os.environ.get("RITAM_TEST_DATABASE_URL")
DB_URL = normalize_database_url(_raw) if _raw else None
pytestmark = pytest.mark.skipif(not DB_URL, reason="RITAM_TEST_DATABASE_URL not set")


def make_pdf(text: str) -> bytes:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    pdf.add_page()
    pdf.multi_cell(0, 6, text)
    return bytes(pdf.output())


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    from app import models  # noqa: F401
    from app.db import Base

    assert DB_URL

    async def reset() -> None:
        engine = create_async_engine(DB_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(reset())
    settings = Settings(
        env="test", database_url=DB_URL, raw_store_dir=str(tmp_path), gemini_api_key=None
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_pdf_upload_parses_pages_dates_and_dedupes(client: TestClient) -> None:
    pdf = make_pdf(
        "Most Important Terms and Conditions. Effective from 28th August 2026. "
        "Annual fee: Rs. 1,000 + GST."
    )
    r = client.post(
        "/api/uploads",
        files={"file": ("mitc.pdf", pdf, "application/pdf")},
        data={"kind": "mitc_pdf"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["doc_type"] == "pdf" and body["page_count"] == 1 and body["authority_tier"] == 1
    assert body["effective_from"] == "2026-08-28" and body["undated"] is False

    again = client.post(
        "/api/uploads",
        files={"file": ("copy.pdf", pdf, "application/pdf")},
        data={"kind": "mitc_pdf"},
    )
    assert again.json()["id"] == body["id"] and again.json()["reused"] is True

    view = client.get(f"/api/sources/{body['id']}/view").json()
    assert "Annual fee" in view["pages"][0]["text"] and view["highlights"] == []


def test_chat_is_redacted_before_storage(client: TestClient) -> None:
    r = client.post(
        "/api/sources/text",
        json={
            "kind": "user_chat",
            "said_at": "2026-09-10",
            "text": "Agent: card 4111 1111 1111 1111, lounge visits 8 per year. Call 9876543210.",
        },
    )
    assert r.status_code == 201, r.text
    view = client.get(f"/api/sources/{r.json()['id']}/view").json()
    text = view["pages"][0]["text"]
    assert "4111" not in text and "9876543210" not in text and "8 per year" in text
    assert r.json()["meta"]["redactions"] == {"CARD": 1, "PHONE": 1}


def test_bad_inputs_are_problem_json(client: TestClient) -> None:
    fake = client.post(
        "/api/uploads", files={"file": ("x.pdf", b"<html>no</html>", "application/pdf")}
    )
    assert fake.status_code == 422 and fake.headers["content-type"].startswith(
        "application/problem+json"
    )
    ssrf = client.post("/api/sources/url", json={"url": "http://169.254.169.254/latest/meta-data"})
    assert ssrf.status_code == 400
    assert client.get("/api/sources/00000000-0000-0000-0000-000000000000").status_code == 404


def test_audit_with_mixed_url_and_text_sources_is_created(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # audit_source rows used to be flushed before the new source rows (FK error).

    async def public(url: str) -> str:
        return url

    monkeypatch.setattr("app.api.audits.check_url", public)
    enqueued: list[tuple[str, str]] = []

    async def fake_enqueue(name: str, *args: str) -> str:
        enqueued.append((name, *args))
        return "test"

    client.app.state.dispatcher.enqueue = fake_enqueue  # type: ignore[attr-defined]
    r = client.post(
        "/api/audits",
        json={
            "question": "Is the annual fee consistent?",
            "sources": [
                {"type": "url", "url": "https://bank.example/card", "kind": "official_page"},
                {
                    "type": "text",
                    "kind": "user_chat",
                    "text": "Agent: annual fee is Rs 500.",
                    "said_at": "2026-10-20",
                },
            ],
        },
    )
    assert r.status_code == 202, r.text
    audit = client.get(f"/api/audits/{r.json()['audit_id']}").json()
    assert len(audit["sources"]) == 2 and enqueued[0][0] == "audit_job"


async def _insert_running_audit() -> str:
    import uuid as _uuid

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.models import Audit, AuditStatus

    assert DB_URL
    engine = create_async_engine(DB_URL)
    aid = _uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            Audit.__table__.insert().values(
                id=aid, question="interrupted?", status=AuditStatus.RUNNING, stats={}, is_demo=False
            )
        )
    await engine.dispose()
    return str(aid)


def test_restart_marks_interrupted_audits_failed(client: TestClient, tmp_path: Path) -> None:
    import asyncio

    aid = asyncio.run(_insert_running_audit())
    settings = Settings(
        _env_file=None,
        env="test",
        database_url=DB_URL,
        redis_url="",
        raw_store_dir=str(tmp_path),
        gemini_api_key=None,
    )
    with TestClient(create_app(settings)) as c:  # startup runs the recovery
        audit = c.get(f"/api/audits/{aid}").json()
    assert audit["status"] == "failed" and "restart" in audit["stats"]["error"]
