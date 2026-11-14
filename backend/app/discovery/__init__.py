"""Source discovery: a verified catalogue first, then web search. Results are tagged official or
third-party by domain."""

from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx

from app.discovery.cards import CatalogueCard, catalogue, match_card
from app.discovery.domains import JUNK_DOMAINS, classify, host, matches
from app.discovery.india import NOT_INDIAN, foreign_issuer, indian_site

__all__ = [
    "Candidate",
    "CatalogueCard",
    "SearchBudgetExhausted",
    "TavilySearch",
    "catalogue",
    "classify",
    "discover",
    "match_card",
    "queries_for",
]

Origin = Literal["catalogue", "search"]


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
    """(query, reason) pairs, at most four per discovery."""
    return [
        (f"{product} most important terms and conditions MITC fees charges", "bank terms and fees"),
        (
            f"{product} credit card features annual fee rewards",
            "official card page and comparison sites",
        ),
        (f"{product} credit card changes devaluation notice 2026", "recent changes and notices"),
        (
            f"{product} cashback reward points redemption value voucher statement credit",
            "how rewards are actually paid",
        ),
    ]


async def discover(
    *,
    question: str,
    product: str | None,
    pack: str = "credit_card",
    search: TavilySearch | None,
    context: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    found: list[Candidate] = []
    seen: set[str] = set()

    def add(c: Candidate) -> None:
        key = c.url.split("#")[0].rstrip("/")
        if key not in seen and len(found) < limit:
            seen.add(key)
            found.append(c)

    # Pasted text (a bank SMS, an ad) only helps identify the card; it is never sent to search.
    card = next(
        (c for t in (product, context, question) if t and (c := match_card(t, pack=pack))), None
    )
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
    # India-only: a card the name already marks as foreign costs no search credit.
    not_indian = card is None and foreign_issuer(product)
    topic = card.name if card else product
    if search is not None and topic and not not_indian and (card is None or len(found) < 4):
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
                if not url.startswith(("http://", "https://")) or matches(host(url), JUNK_DOMAINS):
                    continue
                kind, official = classify(url, title)
                add(Candidate(url, title or url, kind, official, "search", f"Web search: {why}"))

    # ...and an unlisted card whose search found no Indian website at all is not reported on.
    if card is None and searched and found and not any(indian_site(c.url) for c in found):
        not_indian = True
    if not_indian:
        found = []
    found.sort(key=lambda c: (not c.official, c.origin != "catalogue"))
    return {
        "candidates": [c.as_dict() for c in found],
        "not_indian": not_indian,
        "message": NOT_INDIAN if not_indian else None,
        "matched_card": card.name if card else None,
        "searched": searched,
        "search_available": search is not None,
        "errors": errors,
    }
