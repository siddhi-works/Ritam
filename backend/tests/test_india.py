from app.discovery import discover
from app.discovery.india import foreign_issuer, indian_site, looks_indian_card


def test_foreign_issuers_are_named_but_indian_cards_are_not():
    assert foreign_issuer("Chase Sapphire Preferred")
    assert foreign_issuer("Capital One Venture")
    assert not foreign_issuer("HDFC Millennia")
    assert not foreign_issuer("American Express Membership Rewards")  # Amex India is on the list


def test_a_report_needs_some_sign_the_card_is_indian():
    us_page = "Annual fee $95. Purchase APR 21.49% - 28.49% variable. Foreign transaction fee $0."
    in_page = "Annual fee Rs. 499 + GST. Late payment charges as per RBI guidelines."
    assert looks_indian_card("HDFC Millennia", [], [])  # on Ritam's checked list
    assert looks_indian_card("Unlisted Card", ["https://www.sbicard.com/x.pdf"], [us_page])
    assert looks_indian_card("Unlisted Card", ["https://example.com/a"], [in_page])
    assert not looks_indian_card("Unlisted Card", ["https://example.com/a"], [us_page])
    assert not looks_indian_card("Chase Freedom", ["https://www.sbicard.com/x.pdf"], [in_page])


def test_indian_sites():
    assert indian_site("https://www.paisabazaar.com/x")
    assert indian_site("https://www.example.co.in/x")
    assert not indian_site("https://www.nerdwallet.com/x")
    assert not indian_site("https://www.americanexpress.com/us/credit-cards/")


class _Search:
    def __init__(self, results):
        self.results, self.calls = results, 0

    async def search(self, query, **_):
        self.calls += 1
        return self.results


async def test_discovery_refuses_foreign_cards():
    s = _Search([{"url": "https://www.chase.com/x", "title": "x"}])
    out = await discover(question="fees?", product="Chase Sapphire", search=s)  # type: ignore[arg-type]
    assert out["not_indian"] and out["candidates"] == [] and s.calls == 0

    us_only = _Search([{"url": "https://www.nerdwallet.com/card", "title": "Some Card review"}])
    out = await discover(question="fees?", product="Some Card", search=us_only)  # type: ignore[arg-type]
    assert out["not_indian"] and out["candidates"] == []

    mixed = _Search([{"url": "https://www.paisabazaar.com/card", "title": "Some Card"}])
    out = await discover(question="fees?", product="Some Card", search=mixed)  # type: ignore[arg-type]
    assert not out["not_indian"] and out["candidates"]
