import httpx
import pytest
import respx

from app.discovery import (
    SearchBudgetExhausted,
    TavilySearch,
    catalogue,
    classify,
    discover,
    match_card,
)


@pytest.mark.parametrize(
    ("url", "title", "expected"),
    [
        (
            "https://www.hdfc.bank.in/credit-cards/millennia-credit-card",
            "",
            ("official_page", True),
        ),
        ("https://www.axis.bank.in/docs/mitc-credit-cards.pdf", "", ("mitc_pdf", True)),
        ("https://www.kotak.bank.in/files/key-fact-statement-league.pdf", "", ("kfs_pdf", True)),
        (
            "https://campaign.axis.bank.in/x.pdf",
            "Revision in Magnus card terms",
            ("bank_notice", True),
        ),
        ("https://rbi.org.in/Scripts/NotificationUser.aspx?Id=12300", "", ("rbi_rule", True)),
        ("https://scholarships.gov.in/", "National Scholarship Portal", ("official_page", True)),
        ("https://www.paisabazaar.com/hdfc-bank/millennia-credit-card/", "", ("aggregator", False)),
        ("https://www.technofino.in/community/threads/x", "", ("forum", False)),
        ("https://www.livemint.com/money/x", "", ("news", False)),
        # Look-alike host must not be treated as the bank.
        ("https://hdfcbank.com.evil.example/terms", "", ("aggregator", False)),
        ("https://nothdfcbank.com/terms", "", ("aggregator", False)),
    ],
)
def test_classify(url: str, title: str, expected: tuple[str, bool]) -> None:
    assert classify(url, title) == expected


def test_catalogue_loads_and_every_catalogue_kind_is_consistent() -> None:
    cards = catalogue()
    assert len(cards) >= 7
    for card in cards:
        assert card.sources, card.id
        assert any(classify(s["url"])[1] for s in card.sources), f"{card.id} has no official source"
        for s in card.sources:
            assert s["url"].startswith("https://")


@pytest.mark.parametrize(
    ("text", "card_id"),
    [
        ("HDFC Millennia", "hdfc-millennia"),
        ("my hdfc millenia card", "hdfc-millennia"),  # common misspelling
        ("Axis Bank Magnus credit card", "axis-magnus"),
        ("amazon pay icici", "icici-amazon-pay"),
        ("SBI simply click", "sbi-simplyclick"),
    ],
)
def test_match_card(text: str, card_id: str) -> None:
    card = match_card(text)
    assert card is not None and card.id == card_id


def test_match_card_rejects_unrelated() -> None:
    assert match_card("Post-matric scholarship for SC students") is None
    assert match_card("") is None


async def test_discover_catalogue_without_search() -> None:
    out = await discover(question="Is the fee right?", product="axis magnus", search=None)
    assert out["matched_card"] == "Axis Bank Magnus credit card"
    assert out["searched"] is False and out["search_available"] is False
    cands = out["candidates"]
    assert cands and all(c["origin"] == "catalogue" for c in cands)
    officials = [c["official"] for c in cands]
    assert officials == sorted(officials, reverse=True)  # official sources first


@respx.mock
async def test_discover_searches_for_unknown_topic_and_tags_results() -> None:
    route = respx.post("https://api.tavily.com/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"url": "https://www.buddy4study.com/page/nsp", "title": "NSP guide"},
                    {
                        "url": "https://scholarships.gov.in/public/schemeGuidelines",
                        "title": "Guidelines",
                    },
                    {"url": "javascript:alert(1)", "title": "bad"},
                ]
            },
        )
    )
    search = TavilySearch("tvly-test")
    try:
        out = await discover(
            question="Am I eligible?",
            product="Post-matric scholarship",
            pack="general",
            search=search,
        )
    finally:
        await search.aclose()
    assert route.call_count == 3
    sent = route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer tvly-test"
    urls = [c["url"] for c in out["candidates"]]
    assert urls == [
        "https://scholarships.gov.in/public/schemeGuidelines",
        "https://www.buddy4study.com/page/nsp",
    ]  # deduplicated across queries, official first, non-http dropped
    assert out["searched"] is True and out["matched_card"] is None


@respx.mock
async def test_discover_survives_search_errors() -> None:
    respx.post("https://api.tavily.com/search").mock(return_value=httpx.Response(432))
    search = TavilySearch("tvly-test")
    try:
        out = await discover(question="q?", product="Some unknown card", search=search)
    finally:
        await search.aclose()
    assert out["candidates"] == [] and out["searched"] is False
    assert out["errors"] == ["HTTPStatusError"] * 3


async def test_discover_stops_when_search_budget_is_used() -> None:
    class Exhausted:
        calls = 0

        async def search(self, query: str, **kw: object) -> list[dict[str, str]]:
            self.calls += 1
            raise SearchBudgetExhausted

    s = Exhausted()
    out = await discover(question="q?", product="Some unknown card", search=s)  # type: ignore[arg-type]
    assert s.calls == 1 and out["errors"] == ["SearchBudgetExhausted"]


def test_discover_endpoint_works_without_search_key() -> None:
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        _env_file=None, env="test", gemini_api_key=None, neo4j_password=None, tavily_api_key=None,
        database_url="postgresql+asyncpg://u:p@127.0.0.1:1/x", redis_url=None, dependency_timeout_s=1.0,
    )  # fmt: skip
    with TestClient(create_app(settings)) as client:
        ok = client.post(
            "/api/discover", json={"question": "Any hidden fees?", "product": "HDFC Millennia"}
        )
        bad = client.post("/api/discover", json={"question": "x", "pack": "loans"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["matched_card"] == "HDFC Bank Millennia credit card"
    assert body["search_available"] is False and len(body["candidates"]) == 4
    assert bad.status_code == 422


def test_topics_match_only_in_the_general_pack() -> None:
    topic = match_card("NMMS scholarship", pack="general")
    assert topic is not None and topic.id == "nmmss-2026-27" and topic.pack == "general"
    assert match_card("nmmss") is None  # not a credit card
    assert match_card("hdfc millennia", pack="general") is None


@pytest.mark.parametrize(
    "text",
    [
        "IndusInd Legend credit card",  # used to match AU LIT via "credit card" + "lit"
        "hdfc",  # bank alone is not a card
        "HDFC Regalia",  # same bank, different card
        "credit card",
    ],
)
def test_match_card_never_returns_another_card(text: str) -> None:
    assert match_card(text) is None


def test_match_card_tells_hdfc_and_idfc_millennia_apart() -> None:
    hdfc, idfc = match_card("hdfc millenia"), match_card("idfc millennia")
    assert hdfc is not None and hdfc.id == "hdfc-millennia"
    assert idfc is not None and idfc.id == "idfc-first-millennia"


def test_social_media_is_not_an_aggregator() -> None:
    assert classify("https://www.facebook.com/kishtwaradministration/posts/1") == ("forum", False)
