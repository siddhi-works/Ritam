from datetime import date, datetime
from pathlib import Path

import pytest
from fpdf import FPDF

from app.ingest.dates import extract_dates, find_dates
from app.ingest.netguard import BlockedURL, check_url
from app.ingest.parse import PAGE_SEP, ParseError, clean_text, parse, sniff
from app.ingest.redact import redact
from app.storage import LocalStore, sha256


def make_pdf(pages: list[str]) -> bytes:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    for text in pages:
        pdf.add_page()
        pdf.multi_cell(0, 6, text)
    return bytes(pdf.output())


# netguard


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://127.0.0.1/admin",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://localhost:8000/",
        "http://user:pass@example.com/",
        "http://example.com:22/",
        "http://printer.local/",
    ],
)
async def test_guard_blocks_non_public_targets(url: str) -> None:
    with pytest.raises(BlockedURL):
        await check_url(url)


async def test_guard_blocks_hostnames_resolving_to_private_ips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(host: str) -> list[str]:
        return ["93.184.216.34", "192.168.1.10"]  # one private answer is enough to refuse

    monkeypatch.setattr("app.ingest.netguard.resolve", fake_resolve)
    with pytest.raises(BlockedURL):
        await check_url("https://rebind.example/")


async def test_guard_allows_public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str) -> list[str]:
        return ["23.45.67.89"]

    monkeypatch.setattr("app.ingest.netguard.resolve", fake_resolve)
    assert await check_url(" https://www.hdfcbank.com/x ") == "https://www.hdfcbank.com/x"


# parse


def test_pdf_pages_have_consistent_offsets() -> None:
    body = make_pdf(["Annual Fee: Rs. 1,000 + GST", "Late payment charges apply."])
    doc = parse(body, filename="mitc.pdf")
    assert doc.doc_type == "pdf" and len(doc.pages) == 2
    for page in doc.pages:
        assert doc.text[page.char_start : page.char_start + len(page.text)] == page.text
    assert doc.pages[1].char_start == len(doc.pages[0].text) + len(PAGE_SEP)
    assert "Annual Fee" in doc.pages[0].text


def test_pdf_page_limit_and_fake_pdf() -> None:
    from app.ingest.parse import parse_pdf

    with pytest.raises(ParseError, match="limit"):
        parse_pdf(make_pdf(["a", "b", "c"]), max_pages=2)
    with pytest.raises(ParseError, match="not a PDF"):
        sniff(b"<html>hi</html>", filename="x.pdf")


def test_html_extraction_drops_scripts_and_keeps_tables() -> None:
    html = (
        "<html><head><title>Millennia Credit Card</title><script>var x=1;</script></head><body>"
        "<main><h1>Fees and charges</h1>"
        "<table><tr><td>Annual fee</td><td>Rs 1,000</td></tr>"
        "<tr><td>Lounge visits</td><td>8 per year</td></tr></table>"
        + "<p>Terms apply to all cardholders of this product.</p>" * 10
        + "</main></body></html>"
    ).encode()
    doc = parse(html, content_type="text/html")
    assert doc.doc_type == "html" and doc.title == "Millennia Credit Card"
    assert "Rs 1,000" in doc.text and "var x" not in doc.text


def test_clean_text_fixes_ligatures_hyphen_breaks_and_spacing() -> None:
    assert clean_text("beneﬁts  are pro-\ncessed\r\n\n\n\nnext") == (
        "benefits are processed\n\nnext"
    )


# dates


def test_indian_date_formats_and_labels() -> None:
    text = (
        "Notice dated 15th July 2026\n"
        "The revised charges will be effective from 28th August 2026. "
        "Lounge changes w.e.f. 01/09/2026.\n"
        "Last updated on Aug 1, 2026. Ref 2026-07-10."
    )
    got = [(c.value, c.label) for c in find_dates(text)]
    assert got == [
        (date(2026, 7, 15), "announced"),
        (date(2026, 8, 28), "effective"),
        (date(2026, 9, 1), "effective"),  # day-first: 01/09 is 1 Sep, not 9 Jan
        (date(2026, 8, 1), "updated"),
        (date(2026, 7, 10), "unlabelled"),
    ]
    info = extract_dates(text, today=date(2026, 10, 31))
    assert info.effective_from == date(2026, 9, 1)  # latest effective date = current version
    assert info.announced_at == date(2026, 7, 15)
    assert info.published_at == date(2026, 8, 1)
    assert (info.method, info.confidence) == ("text:effective", 0.9)


def test_invalid_and_future_dates_are_ignored() -> None:
    info = extract_dates("dated 31/02/2026. Last updated on 5 Jan 2030.", today=date(2026, 10, 31))
    assert info.announced_at is None and info.published_at is None


def test_pdf_creation_date_alone_stays_below_dated_threshold() -> None:
    info = extract_dates(
        "No dates here.", pdf_dates={"created": datetime(2024, 3, 1)}, today=date(2026, 10, 31)
    )
    assert info.published_at == date(2024, 3, 1)
    assert info.confidence is not None and info.confidence < 0.5


def test_undated_text_has_no_confidence() -> None:
    assert extract_dates("Annual fee Rs 500.", today=date(2026, 10, 31)).confidence is None


# redact


def test_redaction_masks_identifiers_but_keeps_evidence() -> None:
    chat = (
        "Agent: Your card 4111 1111 1111 1111 has annual fee Rs 1,000 "
        "waived on Rs 1,00,000 spend.\n"
        "Me: my PAN is ABCDE1234F, phone +91 98765 43210, mail me@example.com, "
        "A/c no 123456789012.\n"
        "Agent: lounge visits 8 per year from 28/08/2026, forex markup 3.5%."
    )
    out, counts = redact(chat)
    for secret in ("4111", "ABCDE1234F", "98765", "me@example.com", "123456789012"):
        assert secret not in out
    for evidence in ("Rs 1,000", "Rs 1,00,000", "28/08/2026", "3.5%", "8 per year"):
        assert evidence in out
    assert counts["CARD"] == 1 and counts["PAN"] == 1


# storage


async def test_store_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    store = LocalStore(tmp_path)
    digest, rel = await store.put(b"hello")
    assert digest == sha256(b"hello") and rel == f"{digest[:2]}/{digest}"
    assert await store.put(b"hello") == (digest, rel)
    assert await store.get(digest) == b"hello"
    with pytest.raises(ValueError):
        await store.get("../../etc/passwd")


# ingest service helpers


def test_redirect_warning_flags_a_different_product_not_a_domain_move() -> None:
    from app.ingest.service import redirect_warning

    hdfc_old = "https://www.hdfcbank.com/personal/pay/cards/credit-cards/millennia-credit-card"
    assert redirect_warning(
        hdfc_old, "https://www.hdfc.bank.in/credit-cards/regalia-first-credit-card"
    )
    assert (
        redirect_warning(hdfc_old, "https://www.hdfc.bank.in/credit-cards/millennia-credit-card/")
        is None
    )


async def test_thin_js_shell_is_replaced_by_rendered_page() -> None:
    from datetime import UTC, datetime

    from app.config import Settings
    from app.ingest.fetch import FetchResult
    from app.ingest.service import _input_from, _prefer_rendered
    from app.models import Source, SourceKind

    def result(body: bytes, method: str) -> FetchResult:
        return FetchResult(
            "https://b.test/c",
            "https://b.test/c",
            200,
            "text/html",
            body,
            method,
            datetime.now(UTC),
            attempts=[{"method": method, "status": 200}],
        )

    shell = b"<html><title>Card</title><body><div id=root>Loading</div></body></html>"
    full = (
        b"<html><title>Card</title><body><main>"
        + b"<p>Annual fee Rs 500 + GST.</p>" * 80
        + b"</main></body></html>"
    )

    class FakeFetcher:
        has_browser = True

        async def fetch_with_browser(self, url: str) -> FetchResult:
            return result(full, "browser")

    source = Source(kind=SourceKind.OFFICIAL_PAGE, url="https://b.test/c", title=None)
    inp = _input_from(source, result(shell, "httpx"))
    chosen = await _prefer_rendered(inp, source, FakeFetcher(), Settings())  # type: ignore[arg-type]
    assert chosen.fetch is not None and chosen.fetch.method == "browser"
    assert [a["method"] for a in chosen.fetch.attempts] == ["httpx", "httpx", "browser"]


def test_neon_connection_string_is_accepted_unchanged() -> None:
    from app.config import Settings
    from app.db import normalize_database_url

    neon = "postgresql://neondb_owner:pw@ep-x.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert normalize_database_url(neon) == (
        "postgresql+asyncpg://neondb_owner:pw@ep-x.us-east-1.aws.neon.tech/neondb?ssl=require"
    )
    assert Settings(database_url=neon).database_url.startswith("postgresql+asyncpg://")
    local = "postgresql+asyncpg://ritam:ritam@localhost:5432/ritam"
    assert normalize_database_url(local) == local


def test_aura_username_variable_is_preferred(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_USERNAME", "08cf50c4")
    assert Settings(_env_file=None).neo4j_user == "08cf50c4"


async def test_dns_lookup_retries_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import socket

    from app.ingest import netguard

    calls = {"n": 0}

    async def flaky(host: str, port: object, type: int = 0) -> list[tuple[object, ...]]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise socket.gaierror("temporary failure")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("23.222.30.17", 0))]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", flaky)
    assert await netguard.resolve("campaign.axis.bank.in") == ["23.222.30.17"]
    assert calls["n"] == 2
