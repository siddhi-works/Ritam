from datetime import date, timedelta
from decimal import Decimal

from app.benchmarks import MAX_AGE, MIN_CARDS, compute
from app.terms import TermVersion

TODAY = date(2026, 11, 15)


def _v(attr, value, read_on=TODAY, period=None):
    norm = {"type": "percent", "parsed": True, "value": value}
    if period:
        norm["period"] = period
    return TermVersion(attr, f"{value}", norm, None, date(2026, 1, 1), "document", "q", "u", "t", "c",
                       "mitc_pdf", read_on)  # fmt: skip


def test_benchmark_needs_enough_recent_cards():
    cards = [{"forex_markup": [_v("forex_markup", x)]} for x in (2, 2.5, 3.5, 3.5, 1.99)]
    b = compute(cards, TODAY)["forex_markup"]
    assert (b.low, b.median, b.high, b.cards) == (
        Decimal("1.99"),
        Decimal("2.5"),
        Decimal("3.5"),
        5,
    )
    assert "Across 5 cards" in b.text() and "1.99% to 3.5%" in b.text()
    assert "forex_markup" not in compute(cards[: MIN_CARDS - 1], TODAY)


def test_stale_terms_are_left_out():
    old = TODAY - MAX_AGE - timedelta(days=1)
    cards = [{"forex_markup": [_v("forex_markup", 3, read_on=old)]} for _ in range(6)]
    assert compute(cards, TODAY) == {}


def test_yearly_interest_is_shown_per_month():
    cards = [{"finance_charge": [_v("finance_charge", 42, period="year")]} for _ in range(5)]
    assert compute(cards, TODAY)["finance_charge"].median == Decimal("3.5")
