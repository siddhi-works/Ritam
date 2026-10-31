import httpx
import pytest
import respx

from app.ingest.fetch import DomainThrottle, Fetcher, FetchFailed, looks_blocked
from app.ingest.netguard import BlockedURL

PAGE = b"<html><body>" + b"<p>Annual fee Rs 1,000 plus GST.</p>" * 50 + b"</body></html>"


async def allow(url: str) -> str:
    if "evil" in url:
        raise BlockedURL("private")
    return url


async def no_sleep(_: float) -> None:
    return None


class FakeBrowser:
    def __init__(self, html: bytes = PAGE, status: int = 200):
        self.calls: list[str] = []
        self._html, self._status = html, status

    async def fetch_html(self, url: str) -> tuple[str, int, bytes]:
        self.calls.append(url)
        return url, self._status, self._html


def fetcher(client: httpx.AsyncClient, **kw: object) -> Fetcher:
    return Fetcher(
        client,
        guard=allow,
        sleep=no_sleep,
        throttle=DomainThrottle(concurrency=4, interval_s=0),
        **kw,  # type: ignore[arg-type]
    )


@respx.mock
async def test_direct_fetch_success() -> None:
    respx.get("https://bank.test/card").mock(
        return_value=httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})
    )
    async with httpx.AsyncClient() as c:
        res = await fetcher(c).fetch("https://bank.test/card")
    assert res.method == "httpx" and res.body == PAGE and res.archived_at is None
    assert res.attempts == [{"method": "httpx", "status": 200}]


@respx.mock
async def test_redirects_are_revalidated_and_private_redirect_is_refused() -> None:
    respx.get("https://bank.test/a").mock(
        return_value=httpx.Response(302, headers={"location": "http://evil.internal/"})
    )
    async with httpx.AsyncClient() as c:
        # A redirect into a private network is a security refusal, not a "try Wayback" case.
        with pytest.raises(BlockedURL):
            await fetcher(c).fetch("https://bank.test/a")


@respx.mock
async def test_blocked_page_falls_back_to_browser() -> None:
    challenge = b"<html><title>Just a moment...</title>Checking your browser cf-chl</html>"
    respx.get("https://bank.test/card").mock(
        return_value=httpx.Response(403, content=challenge, headers={"content-type": "text/html"})
    )
    browser = FakeBrowser()
    async with httpx.AsyncClient() as c:
        res = await fetcher(c, browser=browser, use_wayback=False).fetch("https://bank.test/card")
    assert res.method == "browser" and browser.calls == ["https://bank.test/card"]
    assert res.attempts[0]["method"] == "httpx" and res.attempts[0]["status"] == 403


@respx.mock
async def test_wayback_fallback_marks_snapshot_time() -> None:
    respx.get("https://bank.test/old.pdf").mock(return_value=httpx.Response(404))
    respx.get("https://archive.org/wayback/available").mock(
        return_value=httpx.Response(
            200,
            json={
                "archived_snapshots": {
                    "closest": {"available": True, "status": "200", "timestamp": "20250102030405"}
                }
            },
        )
    )
    respx.get("https://web.archive.org/web/20250102030405id_/https://bank.test/old.pdf").mock(
        return_value=httpx.Response(
            200, content=b"%PDF-1.4 ...", headers={"content-type": "application/pdf"}
        )
    )
    async with httpx.AsyncClient() as c:
        res = await fetcher(c).fetch("https://bank.test/old.pdf")
    assert res.method == "wayback" and res.requested_url == "https://bank.test/old.pdf"
    assert res.archived_at is not None and res.archived_at.isoformat().startswith(
        "2025-01-02T03:04:05"
    )


@respx.mock
async def test_everything_failing_asks_for_upload() -> None:
    respx.get("https://bank.test/x").mock(return_value=httpx.Response(403))
    respx.get("https://archive.org/wayback/available").mock(
        return_value=httpx.Response(200, json={"archived_snapshots": {}})
    )
    async with httpx.AsyncClient() as c:
        with pytest.raises(FetchFailed, match="Upload the PDF") as exc:
            await fetcher(c).fetch("https://bank.test/x")
    assert [a["method"] for a in exc.value.attempts] == ["httpx", "wayback"]


@respx.mock
async def test_transport_errors_retry_then_succeed() -> None:
    route = respx.get("https://bank.test/x").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, content=PAGE)]
    )
    async with httpx.AsyncClient() as c:
        res = await fetcher(c).fetch("https://bank.test/x")
    assert route.call_count == 2 and res.status == 200


@respx.mock
async def test_oversized_body_is_rejected() -> None:
    respx.get("https://bank.test/big").mock(return_value=httpx.Response(200, content=b"x" * 2048))
    async with httpx.AsyncClient() as c:
        with pytest.raises(FetchFailed) as exc:
            await fetcher(c, max_bytes=1024, use_wayback=False).fetch("https://bank.test/big")
    assert "TooLarge" in str(exc.value.attempts[0]["error"])


async def test_bad_url_is_refused_before_any_request() -> None:
    async with httpx.AsyncClient() as c:
        with pytest.raises(BlockedURL):
            await fetcher(c).fetch("http://evil.internal/")


def test_looks_blocked() -> None:
    assert looks_blocked(403, "text/html", b"")
    assert looks_blocked(200, "text/html", b"<html>Please complete the CAPTCHA</html>")
    assert not looks_blocked(200, "text/html", PAGE)
    assert not looks_blocked(200, "application/pdf", b"%PDF captcha")


@respx.mock
async def test_jina_reader_renders_js_page_as_text() -> None:
    from app.ingest.fetch import JinaReaderFetcher

    respx.get("https://reader.test/https://bank.test/card").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "title": "Magnus Card",
                    "url": "https://bank.test/card",
                    "content": "Annual fee Rs 12,500 + GST " * 100,
                }
            },
        )
    )
    async with httpx.AsyncClient() as c:
        f = fetcher(
            c, browser=JinaReaderFetcher("https://reader.test/", client=c), use_wayback=False
        )
        res = await f.fetch_with_browser("https://bank.test/card")
    assert res.method == "browser" and res.content_type == "text/plain"
    assert res.body.decode().startswith("# Magnus Card") and len(res.body) > 1500


def test_fetcher_factory_modes() -> None:
    from app.ingest.fetch import JinaReaderFetcher, make_fetcher

    assert not make_fetcher("none").has_browser
    assert isinstance(make_fetcher("jina")._browser, JinaReaderFetcher)
