"""Fetch chain: httpx, then a headless browser, then the Wayback Machine. Wayback copies carry their
snapshot time."""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from app.ingest.netguard import BlockedURL, check_url

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 Ritam/0.1"
)
_BLOCK_STATUSES = {401, 403, 407, 429, 451, 503}
_BLOCK_MARKERS = (
    "captcha",
    "access denied",
    "are you a robot",
    "request unsuccessful",
    "cf-chl",
    "incapsula",
    "just a moment...",
    "enable javascript and cookies",
)
_WAYBACK_API = "https://archive.org/wayback/available"


class FetchFailed(Exception):
    def __init__(self, message: str, attempts: list[dict[str, object]]):
        super().__init__(message)
        self.attempts = attempts


class TooLarge(Exception):
    pass


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    method: str  # httpx | browser | wayback
    fetched_at: datetime
    archived_at: datetime | None = None  # Wayback snapshot time
    attempts: list[dict[str, object]] = field(default_factory=list)


class BrowserFetcher(Protocol):
    async def fetch_html(self, url: str) -> tuple[str, int, bytes]: ...


def looks_blocked(status: int, content_type: str, body: bytes) -> bool:
    if status in _BLOCK_STATUSES:
        return True
    if "html" not in content_type or len(body) > 200_000:
        return False
    head = body[:20_000].decode("utf-8", "ignore").lower()
    return any(m in head for m in _BLOCK_MARKERS) and len(body) < 50_000


class DomainThrottle:
    """At most `concurrency` requests per host, at least `interval_s` apart (in-process)."""

    def __init__(self, concurrency: int = 2, interval_s: float = 1.0):
        self._concurrency = concurrency
        self._interval = interval_s
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._last: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def __call__(self, host: str) -> asyncio.Semaphore:
        async with self._lock:
            sem = self._sems.setdefault(host, asyncio.Semaphore(self._concurrency))
        await sem.acquire()
        async with self._lock:
            wait = self._last.get(host, 0.0) + self._interval - time.monotonic()
            self._last[host] = max(time.monotonic(), self._last.get(host, 0.0) + self._interval)
        if wait > 0:
            await asyncio.sleep(wait)
        return sem


class Fetcher:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        max_bytes: int = 20 * 1024 * 1024,
        max_redirects: int = 3,
        timeout_s: float = 20.0,
        retries: int = 3,
        browser: BrowserFetcher | None = None,
        use_wayback: bool = True,
        guard: Callable[[str], Awaitable[str]] = check_url,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        throttle: DomainThrottle | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=timeout_s, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-IN,en"}
        )
        self._owns_client = client is None
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._retries = retries
        self._browser = browser
        self._use_wayback = use_wayback
        self._guard = guard
        self._sleep = sleep
        self._throttle = throttle or DomainThrottle()

    @property
    def has_browser(self) -> bool:
        return self._browser is not None

    async def fetch_with_browser(self, url: str) -> FetchResult:
        """Re-fetch through the headless browser, e.g. when plain HTTP returned a JS shell."""
        url = await self._guard(url)
        result = await self._fetch_browser(url)
        result.attempts = [{"method": "browser", "status": result.status}]
        return result

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch(self, url: str) -> FetchResult:
        url = await self._guard(url)  # BlockedURL propagates: never fall back for a bad URL
        attempts: list[dict[str, object]] = []

        result = await self._try("httpx", attempts, self._fetch_direct(url))
        if result is None and self._browser is not None:
            result = await self._try("browser", attempts, self._fetch_browser(url))
        if result is None and self._use_wayback:
            result = await self._try("wayback", attempts, self._fetch_wayback(url))
        if result is None:
            raise FetchFailed(
                "Could not fetch this page (it may block automated access). "
                "Upload the PDF or paste the text instead.",
                attempts,
            )
        result.attempts = attempts
        return result

    async def _try(
        self, method: str, attempts: list[dict[str, object]], job: Awaitable[FetchResult | None]
    ) -> FetchResult | None:
        try:
            result = await job
        except BlockedURL:
            raise
        except Exception as exc:  # noqa: BLE001 - any step failing (incl. Playwright errors) → next step
            attempts.append({"method": method, "error": f"{type(exc).__name__}: {exc}"[:300]})
            return None
        if result is None:
            attempts.append({"method": method, "error": "no result"})
            return None
        if result.status != 200 or looks_blocked(result.status, result.content_type, result.body):
            attempts.append(
                {"method": method, "status": result.status, "error": "blocked or not 200"}
            )
            return None
        attempts.append({"method": method, "status": 200})
        return result

    async def _fetch_direct(self, url: str) -> FetchResult:
        for attempt in range(1, self._retries + 1):
            try:
                return await self._get_following_redirects(url, method="httpx")
            except httpx.TransportError:
                if attempt == self._retries:
                    raise
            await self._sleep(min(2 ** (attempt - 1), 8) + random.uniform(0, 0.5))  # noqa: S311
        raise RuntimeError("unreachable")

    async def _get_following_redirects(self, url: str, *, method: str) -> FetchResult:
        current = url
        for _ in range(self._max_redirects + 1):
            sem = await self._throttle(urlsplit(current).hostname or "")
            try:
                async with self._client.stream("GET", current, follow_redirects=False) as resp:
                    if resp.is_redirect and "location" in resp.headers:
                        current = await self._guard(urljoin(current, resp.headers["location"]))
                        continue
                    if resp.status_code >= 500:
                        raise httpx.TransportError(f"server error {resp.status_code}")
                    body = await self._read_capped(resp)
                    return FetchResult(
                        requested_url=url,
                        final_url=current,
                        status=resp.status_code,
                        content_type=resp.headers.get("content-type", "").lower(),
                        body=body,
                        method=method,
                        fetched_at=datetime.now(UTC),
                    )
            finally:
                sem.release()
        raise httpx.TooManyRedirects(f"more than {self._max_redirects} redirects")

    async def _read_capped(self, resp: httpx.Response) -> bytes:
        declared = resp.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._max_bytes:
            raise TooLarge(f"{declared} bytes exceeds limit")
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > self._max_bytes:
                raise TooLarge(f"body exceeds {self._max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _fetch_browser(self, url: str) -> FetchResult:
        assert self._browser is not None
        final_url, status, html = await self._browser.fetch_html(url)
        await self._guard(final_url)
        return FetchResult(
            requested_url=url,
            final_url=final_url,
            status=status,
            content_type=getattr(self._browser, "content_type", "text/html"),
            body=html,
            method="browser",
            fetched_at=datetime.now(UTC),
        )

    async def _fetch_wayback(self, url: str) -> FetchResult | None:
        resp = await self._client.get(_WAYBACK_API, params={"url": url})
        resp.raise_for_status()
        closest = resp.json().get("archived_snapshots", {}).get("closest") or {}
        if not closest.get("available") or str(closest.get("status")) != "200":
            return None
        ts = str(closest["timestamp"])
        # "id_" returns the original bytes without the Wayback toolbar/rewriting.
        snapshot = f"https://web.archive.org/web/{ts}id_/{url}"
        result = await self._get_following_redirects(snapshot, method="wayback")
        result.requested_url = url
        result.archived_at = datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        return result


class PlaywrightFetcher:
    """Headless Chromium for pages that block plain HTTP clients. Optional dependency."""

    def __init__(self, timeout_ms: int = 30_000):
        self._timeout_ms = timeout_ms

    @staticmethod
    def available() -> bool:
        try:
            import playwright.async_api  # noqa: F401
        except ImportError:
            return False
        return True

    async def fetch_html(self, url: str) -> tuple[str, int, bytes]:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(user_agent=USER_AGENT, locale="en-IN")
                resp = await page.goto(url, wait_until="networkidle", timeout=self._timeout_ms)
                html = await page.content()
                return page.url, resp.status if resp else 0, html.encode("utf-8")
            finally:
                await browser.close()


class JinaReaderFetcher:
    """Rendering through Jina Reader (r.jina.ai) for hosts too small for Chromium. Returns text, not
    HTML."""

    content_type = "text/plain"

    def __init__(
        self,
        base_url: str = "https://r.jina.ai/",
        *,
        rpm: int = 18,
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ):
        from app.llm.ratelimit import TokenBucket

        self._base = base_url.rstrip("/") + "/"
        self._bucket = TokenBucket(rpm)
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    async def fetch_html(self, url: str) -> tuple[str, int, bytes]:
        await self._bucket.acquire()
        resp = await self._client.get(
            self._base + url,
            headers={"Accept": "application/json", "X-No-Cache": "true", "DNT": "1"},
        )
        if resp.status_code != 200:
            return url, resp.status_code, b""
        data = resp.json().get("data") or {}
        title = str(data.get("title") or "").strip()
        content = str(data.get("content") or "")
        text = (f"# {title}\n\n" if title else "") + content
        return str(data.get("url") or url), 200, text.encode("utf-8")


def make_fetcher(js_fallback: str = "auto") -> "Fetcher":
    """auto: Playwright if installed (local dev), else Jina Reader (small cloud hosts)."""
    browser: BrowserFetcher | None
    if js_fallback == "none":
        browser = None
    elif js_fallback == "playwright" or (js_fallback == "auto" and PlaywrightFetcher.available()):
        browser = PlaywrightFetcher()
    else:
        browser = JinaReaderFetcher()
    return Fetcher(browser=browser)
