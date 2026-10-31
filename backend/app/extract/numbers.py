"""Number parsing with Indian notation: 1,00,000, lakh, crore, Rs./INR/₹, Devanagari digits."""

import re
from decimal import Decimal, InvalidOperation

_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
_NUM = re.compile(
    r"(?<![\w])(?<!\d\.)(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.(\d+))?\s*(lakhs?|lacs?|crores?|cr|k)?(?![\w])",
    re.I,
)
_MULT = {"lakh": 100_000, "lac": 100_000, "crore": 10_000_000, "cr": 10_000_000, "k": 1_000}


def ascii_digits(text: str) -> str:
    return text.translate(_DEVANAGARI)


def number_tokens(text: str) -> list[frozenset[Decimal]]:
    """One entry per number written in `text`: the values it may stand for. "2.5 lakh" →
    {2.5, 250000}; "1,00,000" → {100000}."""
    out: list[frozenset[Decimal]] = []
    for m in _NUM.finditer(ascii_digits(text)):
        whole, frac, mult = m.group(1), m.group(2), m.group(3)
        try:
            value = Decimal(whole.replace(",", "") + (f".{frac}" if frac else ""))
        except InvalidOperation:
            continue
        forms = {value.normalize()}
        if mult:
            forms.add((value * _MULT[mult.lower().rstrip("s")]).normalize())
        out.append(frozenset(forms))
    return out


def numbers_in(text: str) -> set[Decimal]:
    return {v for token in number_tokens(text) for v in token}


def numbers_supported(claimed: str, evidence: str) -> bool:
    """True if every number in `claimed` also appears in `evidence`."""
    available = numbers_in(evidence)
    return all(token & available for token in number_tokens(claimed))
