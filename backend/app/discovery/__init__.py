"""Source discovery: a verified catalogue first, then web search. Results are tagged official or
third-party by domain."""

import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import yaml
from rapidfuzz import fuzz

Origin = Literal["catalogue", "search"]

# Banks and card issuers. RBI reserves the .bank.in domain for regulated banks, so any *.bank.in
# host is treated as official as well.
ISSUER_DOMAINS = {
    "hdfcbank.com", "axisbank.com", "icicibank.com", "sbicard.com", "sbi.co.in", "kotak.com",
    "idfcfirstbank.com", "aubank.in", "indusind.com", "yesbank.in", "rblbank.com", "bankofbaroda.in",
    "pnbindia.in", "federalbank.co.in", "hsbc.co.in", "sc.com", "americanexpress.com", "onecard.app",
}  # fmt: skip
REGULATOR_DOMAINS = {"rbi.org.in", "cms.rbi.org.in", "sebi.gov.in", "npci.org.in"}
GOV_SUFFIXES = (".gov.in", ".nic.in", ".ac.in", ".edu.in")
AGGREGATOR_DOMAINS = {
    "paisabazaar.com", "bankbazaar.com", "cardinsider.com", "cardexpert.in", "groww.in", "finology.in",
    "cardadvisor.in", "wishfin.com", "bajajfinservmarkets.in", "creditkaro.com", "magicpin.in",
    }  # fmt: skip
FORUM_DOMAINS = {
    "technofino.in", "reddit.com", "quora.com", "facebook.com", "x.com", "twitter.com", "instagram.com",
    "youtube.com", "linkedin.com",
}  # fmt: skip
NEWS_DOMAINS = {
    "economictimes.indiatimes.com", "livemint.com", "business-standard.com", "businesstoday.in",
    "moneycontrol.com", "financialexpress.com", "ndtvprofit.com", "thehindubusinessline.com",
    "timesofindia.indiatimes.com", "hindustantimes.com", "indianexpress.com", "news18.com",
}  # fmt: skip


@dataclass(frozen=True)
class Candidate:
    url: str
    title: str
    kind: str
    official: bool
    origin: Origin
    why: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _matches(host: str, domains: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def classify(url: str, title: str = "") -> tuple[str, bool]:
    """(kind, official) from the URL and title."""
    host = _host(url)
    text = f"{url} {title}".lower()
    is_pdf = urlsplit(url).path.lower().endswith(".pdf")
    if _matches(host, REGULATOR_DOMAINS):
        return "rbi_rule", True
    official = (
        host.endswith(".bank.in") or _matches(host, ISSUER_DOMAINS) or host.endswith(GOV_SUFFIXES)
    )
    if official:
        if re.search(r"\bkfs\b|key[- ]fact", text):
            return "kfs_pdf", True
        if re.search(r"mitc|most[- ]important[- ]terms", text):
            return "mitc_pdf", True
        if re.search(r"notice|revision|revised|changes? in", text):
            return "bank_notice", True
        return (
            "mitc_pdf"
            if is_pdf and re.search(r"terms|t&c|tnc|conditions", text)
            else "official_page"
        ), True
    if _matches(host, FORUM_DOMAINS):
        return "forum", False
    if _matches(host, NEWS_DOMAINS):
        return "news", False
    return "aggregator", False  # comparison sites and other third-party pages


@dataclass(frozen=True)
class CatalogueCard:
    id: str
    bank: str
    name: str
    aliases: tuple[str, ...]
    sources: tuple[dict[str, str], ...]
    pack: str = "credit_card"


@lru_cache
def catalogue() -> tuple[CatalogueCard, ...]:
    raw = yaml.safe_load(
        resources.files(__package__).joinpath("catalogue.yaml").read_text(encoding="utf-8")
    )
    return tuple(
        CatalogueCard(
            c["id"], c["bank"], c["name"], tuple(c.get("aliases", [])), tuple(c["sources"]), pack
        )
        for section, pack in (("cards", "credit_card"),)
        for c in raw.get(section) or []
    )


# Words every card or scheme name shares; they must never be what makes two names match
# ("IndusInd Legend credit card" is not "AU LIT credit card").
_GENERIC = {
    "credit", "card", "cards", "bank", "the", "my", "a", "of", "for", "and", "first",
    "small", "finance",
}  # fmt: skip


def _distinctive(text: str) -> list[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
    return [w for w in words if w not in _GENERIC and not w.isdigit()]


def _same_word(a: str, b: str) -> bool:
    # Typos are tolerated only on longer words: "millenia" ~ "millennia", but "lit" != "list".
    return a == b or (min(len(a), len(b)) > 3 and fuzz.ratio(a, b) >= 85)


def match_card(text: str, pack: str = "credit_card") -> CatalogueCard | None:
    """Catalogue entry whose distinctive words all appear in `text`; the most specific alias wins."""
    query = _distinctive(text)
    if not query:
        return None
    best: tuple[int, CatalogueCard] | None = None
    for card in (c for c in catalogue() if c.pack == pack):
        for name in (card.name, *card.aliases):
            words = _distinctive(name)
            if words and all(any(_same_word(w, q) for q in query) for w in words):
                score = sum(len(w) for w in words)
                if best is None or score > best[0]:
                    best = (score, card)
    return best[1] if best else None


class SearchBudgetExhausted(Exception):
    """Raised by a search wrapper when today's search cap is used up."""


class TavilySearch:
    """Tavily search API (basic depth, one credit per call)."""

    def __init__(
        self, api_key: str, *, client: httpx.AsyncClient | None = None, timeout_s: float = 20.0
    ):
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    async def search(
        self, query: str, *, max_results: int = 5, include_domains: list[str] | None = None
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "country": "india",
        }
        if include_domains:
            body["include_domains"] = include_domains
            body["include_domains_mode"] = "prefer"
        resp = await self._client.post(
            "https://api.tavily.com/search",
            json=body,
            headers={"Authorization": f"Bearer {self._key}"},
        )
        resp.raise_for_status()
        return list(resp.json().get("results") or [])

    async def aclose(self) -> None:
        await self._client.aclose()


def queries_for(product: str, question: str, pack: str) -> list[tuple[str, str]]:
    """(query, reason) pairs, at most three per discovery."""
    return [
        (f"{product} most important terms and conditions MITC fees charges", "bank terms and fees"),
        (
            f"{product} credit card features annual fee rewards",
            "official card page and comparison sites",
        ),
        (f"{product} credit card changes devaluation notice 2026", "recent changes and notices"),
    ]


async def discover(
    *,
    question: str,
    product: str | None,
    pack: str = "credit_card",
    search: TavilySearch | None,
    limit: int = 8,
) -> dict[str, Any]:
    found: list[Candidate] = []
    seen: set[str] = set()

    def add(c: Candidate) -> None:
        key = c.url.split("#")[0].rstrip("/")
        if key not in seen and len(found) < limit:
            seen.add(key)
            found.append(c)

    card = match_card(product or question, pack=pack)
    if card:
        for s in card.sources:
            kind, official = s["kind"], classify(s["url"])[1]
            add(
                Candidate(
                    s["url"],
                    s.get("title") or s["url"],
                    kind,
                    official,
                    "catalogue",
                    "Verified source",
                )
            )

    searched = False
    errors: list[str] = []
    if search is not None and (card is None or len(found) < 4):
        topic = card.name if card else (product or question)
        for q, why in queries_for(topic, question, pack):
            try:
                results = await search.search(q, max_results=5)
            except Exception as exc:  # noqa: BLE001 - search is best effort; the catalogue still answers
                errors.append(type(exc).__name__)
                if isinstance(exc, SearchBudgetExhausted):
                    break
                continue
            searched = True
            for r in sorted(
                results, key=lambda r: not classify(r.get("url", ""), r.get("title", ""))[1]
            ):
                url, title = r.get("url") or "", r.get("title") or ""
                if not url.startswith(("http://", "https://")):
                    continue
                kind, official = classify(url, title)
                add(Candidate(url, title or url, kind, official, "search", f"Web search: {why}"))

    found.sort(key=lambda c: (not c.official, c.origin != "catalogue"))
    return {
        "candidates": [c.as_dict() for c in found],
        "matched_card": card.name if card else None,
        "searched": searched,
        "search_available": search is not None,
        "errors": errors,
    }
