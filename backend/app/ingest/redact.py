"""Mask personal identifiers in chats before storage or any LLM call. Amounts, dates and percentages
are kept."""

import re

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    # Card numbers: 13-19 digits, optionally grouped by spaces/dashes.
    ("CARD", re.compile(r"\b(?:\d[ -]?){12,18}\d\b")),
    ("AADHAAR", re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")),
    ("PHONE", re.compile(r"(?<![\d₹.,])(?:\+91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}\b")),
    ("ACCOUNT", re.compile(r"(?i)(?<=a/c)\s*(?:no\.?|number)?\s*[:#-]?\s*\d{6,18}\b")),
    ("ACCOUNT", re.compile(r"(?i)(?<=account)\s*(?:no\.?|number)?\s*[:#-]?\s*\d{6,18}\b")),
]


def redact(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for label, pattern in _RULES:
        text, n = pattern.subn(f"[{label}]", text)
        if n:
            counts[label] = counts.get(label, 0) + n
    return text, counts
