"""Market benchmarks for the card finder, computed from banks' own documents that Ritam has read,
never typed in by hand. A benchmark is shown only when it rests on enough cards whose terms were
read recently; otherwise the card finder simply says what to check. So a figure can't quietly go
out of date."""

import statistics
import time
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.advisor import percent, rupees
from app.discovery import catalogue
from app.terms import TermVersion, in_force, load_terms

MIN_CARDS = 5
MAX_AGE = timedelta(days=180)
CACHE_SECONDS = 6 * 3600

# attribute -> (unit, how to word it)
ATTRIBUTES: dict[str, tuple[str, str]] = {
    "forex_markup": ("percent", "foreign currency markup"),
    "annual_fee": ("money", "annual fee"),
    "annual_fee_waiver": ("money", "spend needed to waive the annual fee"),
    "finance_charge": ("percent_month", "interest when a balance carries over"),
    "domestic_lounge_visits": ("count", "domestic lounge visits a year"),
}


@dataclass(frozen=True)
class Benchmark:
    attribute: str
    low: Decimal
    median: Decimal
    high: Decimal
    cards: int
    oldest_read: date

    def text(self) -> str:
        unit, name = ATTRIBUTES[self.attribute]
        fmt = _formatter(unit)
        span = f"{fmt(self.low)} to {fmt(self.high)}" if self.low != self.high else fmt(self.low)
        return (
            f"Across {self.cards} cards Ritam has checked, the {name} is {span} "
            f"(typical {fmt(self.median)}; banks' own terms, read since {self.oldest_read:%B %Y})."
        )


def _formatter(unit: str) -> Any:
    if unit == "money":
        return rupees
    if unit == "percent":
        return lambda v: percent(v, 2)  # banks quote rates like 1.99%
    if unit == "percent_month":
        return lambda v: f"{percent(v, 2)} a month"
    return lambda v: f"{int(v)}"


def _number(v: TermVersion, unit: str) -> Decimal | None:
    norm = v.norm or {}
    value = norm.get("value")
    if not isinstance(value, int | float) or value < 0:
        return None
    n = Decimal(str(value))
    if unit == "percent_month" and norm.get("period") == "year":
        n = n / 12
    return n


def compute(per_card: list[dict[str, list[TermVersion]]], today: date) -> dict[str, Benchmark]:
    """One value per card (its middle value when terms list several, such as fee slabs), from terms
    in force today and read within MAX_AGE; then the spread across cards."""
    out: dict[str, Benchmark] = {}
    for attr, (unit, _) in ATTRIBUTES.items():
        values: list[Decimal] = []
        reads: list[date] = []
        for by_attr in per_card:
            snap = in_force(by_attr.get(attr, []), today)
            if snap is None:
                continue
            fresh = [v for v in snap.values if v.read_on and today - v.read_on <= MAX_AGE]
            nums = [n for v in fresh if (n := _number(v, unit)) is not None]
            if nums:
                values.append(Decimal(str(statistics.median(nums))))
                reads.append(min(v.read_on for v in fresh if v.read_on))
        if len(values) >= MIN_CARDS:
            out[attr] = Benchmark(
                attr,
                min(values),
                Decimal(str(statistics.median(values))),
                max(values),
                len(values),
                min(reads),
            )
    return out


_cache: tuple[float, dict[str, str]] | None = None


async def benchmark_texts(session: AsyncSession) -> dict[str, str]:
    """Benchmarks as sentences, keyed by attribute; cached for a few hours."""
    global _cache
    if _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    per_card = [await load_terms(session, c.name) for c in catalogue() if c.pack == "credit_card"]
    texts = {k: b.text() for k, b in compute(per_card, date.today()).items()}
    _cache = (time.monotonic(), texts)
    return texts
