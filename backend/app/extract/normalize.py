"""Normalise raw claim values ("Rs. 1,000 + GST", "3.75% per month") into comparable dicts.
Unparseable values stay as text with parsed=False."""

import re
from decimal import Decimal
from typing import Any

from app.extract.numbers import ascii_digits, number_tokens
from app.ingest.dates import find_dates
from app.packs import ValueType

_ZERO = re.compile(
    r"\b(nil|free|no (?:charge|fee)s?|waived|zero|not applicable|n/a|n\.a\.)(?!\w)", re.I
)
_GST = re.compile(r"\b(gst|taxes|tax)\b", re.I)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent)", re.I)
_PERIODS: list[tuple[str, re.Pattern[str]]] = [
    ("month", re.compile(r"\b(per month|p\.?\s?m\.?|monthly|a month|every month)\b", re.I)),
    ("quarter", re.compile(r"\b(per quarter|quarterly|a quarter|every quarter|each quarter)\b", re.I)),  # noqa: E501
    ("year", re.compile(r"\b(per annum|p\.?\s?a\.?|per year|annual(?:ly)?|a year|calendar year|yearly|each year)\b", re.I)),  # noqa: E501
    ("statement", re.compile(r"\b(per statement|statement cycle|billing cycle|per cycle)\b", re.I)),
    ("transaction", re.compile(r"\b(per transaction|each transaction|per txn)\b", re.I)),
]  # fmt: skip
_PER_YEAR = {"month": 12, "quarter": 4, "year": 1}
_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
}  # fmt: skip
_WORD_NUM_RE = re.compile(r"\b(" + "|".join(_WORD_NUMS) + r")\b", re.I)
_DAYS = re.compile(r"(\d+)\s*(day|days|month|months|week|weeks)\b", re.I)


def _period(text: str) -> str | None:
    for name, pattern in _PERIODS:
        if pattern.search(text):
            return name
    return None


def _first_number(text: str) -> Decimal | None:
    tokens = number_tokens(text)
    return max(tokens[0]) if tokens else None  # the multiplied form if "lakh"/"crore"


def _num(d: Decimal) -> float | int:
    return int(d) if d == d.to_integral_value() else float(d)


def _words_to_digits(text: str) -> str:
    return _WORD_NUM_RE.sub(lambda m: str(_WORD_NUMS[m.group(1).lower()]), text)


def normalize_value(raw: str, value_type: ValueType) -> dict[str, Any]:
    text = ascii_digits(raw).strip()
    base: dict[str, Any] = {"type": value_type, "parsed": True}
    if value_type == "text":
        return {**base, "text": re.sub(r"\s+", " ", text.lower())}
    if value_type == "date":  # deadlines, last dates: Indian day-first formats
        found = find_dates(text)
        if (
            len({c.value for c in found}) != 1
        ):  # none, or a range like "1 Jul to 31 Oct": keep as text
            return {"type": "text", "parsed": False, "text": text.lower()}
        return {**base, "value": found[0].value.isoformat()}

    if value_type == "money":
        pct = _PERCENT.search(text)
        amount = _first_number(_PERCENT.sub(" ", text))
        if amount is None and _ZERO.search(text):
            amount = Decimal(0)
        if amount is None and pct is None:
            return {"type": "text", "parsed": False, "text": text.lower()}
        out = {**base, "currency": "INR", "plus_gst": bool(_GST.search(text))}
        if amount is not None:
            out["value"] = _num(amount)
        if pct is not None:
            out["percent"] = _num(Decimal(pct.group(1)))
        if period := _period(text):
            out["period"] = period
        return out

    if value_type == "percent":
        pct = _PERCENT.search(text)
        if pct is None:
            if _ZERO.search(text):
                return {**base, "value": 0, "period": _period(text)}
            return {"type": "text", "parsed": False, "text": text.lower()}
        value = Decimal(pct.group(1))
        period = _period(text)
        out = {**base, "value": _num(value), "period": period}
        if period == "month":
            out["annualised"] = _num(value * 12)
        return out

    if value_type == "count":
        text = _words_to_digits(text)
        if re.search(r"\bunlimited\b", text, re.I):
            return {**base, "value": None, "unlimited": True, "period": _period(text)}
        n = _first_number(text)
        if n is None:
            if _ZERO.search(text) or re.search(r"\bno\b", text, re.I):
                return {**base, "value": 0, "period": _period(text)}
            return {"type": "text", "parsed": False, "text": text.lower()}
        period = _period(text)
        out = {**base, "value": _num(n), "period": period}
        if period in _PER_YEAR:
            out["per_year"] = _num(n * _PER_YEAR[period])
        return out

    # days
    text = _words_to_digits(text)
    m = _DAYS.search(text)
    if m is None:
        return {"type": "text", "parsed": False, "text": text.lower()}
    n, unit = Decimal(m.group(1)), m.group(2).lower()
    days = n * 30 if unit.startswith("month") else n * 7 if unit.startswith("week") else n
    return {**base, "value": _num(days), "unit_written": unit}
