"""Dates in Indian documents: numeric dates are day-first and labelled by the phrase before them. A
PDF timestamp alone stays below the 0.5 confidence bar."""

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

Label = Literal["effective", "announced", "updated", "unlabelled"]

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
_MON = r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"  # noqa: E501
_DAY = r"(?P<day>[0-3]?\d)(?:st|nd|rd|th)?"
_YEAR = r"(?P<year>(?:19|20)\d{2})"

_PATTERNS = [
    re.compile(rf"\b{_DAY}(?:\s+of)?[\s\-/.,]+{_MON}[\s\-/.,]+{_YEAR}\b", re.I),  # 28th Aug, 2026
    re.compile(rf"\b{_MON}\s+{_DAY},?\s+{_YEAR}\b", re.I),  # August 28, 2026
    re.compile(r"\b(?P<year>(?:19|20)\d{2})-(?P<month>[01]?\d)-(?P<day>[0-3]?\d)\b"),  # ISO
    re.compile(r"\b(?P<day>[0-3]?\d)[./-](?P<month>[01]?\d)[./-](?P<year>(?:19|20)\d{2})\b"),
]

_LABELS: list[tuple[Label, re.Pattern[str]]] = [
    (
        "effective",
        re.compile(
            r"(effective\s+(?:from|date|on|w\.?e\.?f\.?)|with\s+effect\s+from|w\.?\s?e\.?\s?f\.?"
            r"|applicable\s+(?:from|w\.?e\.?f\.?)|will\s+be\s+effective|come\s+into\s+(?:force|effect)"
            r"|effective)\W*(?:\w+\W+){0,3}$",
            re.I,
        ),
    ),
    (
        "updated",
        re.compile(
            r"(last\s+(?:updated|modified|revised)|updated\s+on|revised\s+on|as\s+on)\W*$", re.I
        ),
    ),
    (
        "announced",
        re.compile(
            r"(\bdated?\b|issued\s+on|published\s+on|notice\s+date|circular\s+no\.?.{0,40})\W*$",
            re.I,
        ),
    ),
]
_WINDOW = 60


@dataclass(frozen=True)
class DateCandidate:
    value: date
    label: Label
    char_start: int
    snippet: str


@dataclass
class DateInfo:
    published_at: date | None = None
    effective_from: date | None = None
    announced_at: date | None = None
    method: str | None = None
    confidence: float | None = None
    candidates: list[DateCandidate] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "confidence": self.confidence,
            "candidates": [
                {**asdict(c), "value": c.value.isoformat()} for c in self.candidates[:50]
            ],
        }


def _to_date(m: re.Match[str]) -> date | None:
    g = m.groupdict()
    month = _MONTHS[g["mon"][:3].lower()] if g.get("mon") else int(g["month"])
    try:
        d = date(int(g["year"]), month, int(g["day"]))
    except ValueError:
        return None
    return d if 2000 <= d.year <= 2035 else None


def _label(text: str, start: int) -> Label:
    window = text[max(0, start - _WINDOW) : start]
    window = window.split("\n\n")[-1]  # don't let a label leak across paragraphs
    for label, pattern in _LABELS:
        if pattern.search(window):
            return label
    return "unlabelled"


def find_dates(text: str) -> list[DateCandidate]:
    seen: set[tuple[int, int]] = set()
    out: list[DateCandidate] = []
    for pattern in _PATTERNS:
        for m in pattern.finditer(text):
            if any(s <= m.start() < e for s, e in seen):
                continue
            value = _to_date(m)
            if value is None:
                continue
            seen.add((m.start(), m.end()))
            snippet = text[max(0, m.start() - 50) : m.end() + 20].replace("\n", " ")
            out.append(DateCandidate(value, _label(text, m.start()), m.start(), snippet.strip()))
    return sorted(out, key=lambda c: c.char_start)


def extract_dates(
    text: str,
    *,
    html: str | None = None,
    pdf_dates: dict[str, datetime] | None = None,
    today: date | None = None,
) -> DateInfo:
    today = today or date.today()
    tomorrow = today + timedelta(days=1)
    cands = find_dates(text)
    info = DateInfo(candidates=cands)
    picks: list[tuple[str, float]] = []

    effective = [c.value for c in cands if c.label == "effective"]
    if effective:
        # Pages often keep old "effective from" lines, so the latest one wins.
        info.effective_from = max(effective)
        picks.append(("text:effective", 0.9))

    announced = [c for c in cands if c.label == "announced" and c.value <= tomorrow]
    if announced:
        head = [c for c in announced if c.char_start < 1500]
        info.announced_at = (head or announced)[0].value
        picks.append(("text:dated", 0.7 if head else 0.6))

    updated = [c.value for c in cands if c.label == "updated" and c.value <= tomorrow]
    if updated:
        info.published_at = max(updated)
        picks.append(("text:updated", 0.8))
    elif html:
        found = _htmldate(html, today)
        if found:
            info.published_at = found
            picks.append(("htmldate", 0.7))
    if info.published_at is None and info.announced_at is not None:
        info.published_at = info.announced_at
    if info.published_at is None and pdf_dates:
        for key, conf in (("modified", 0.45), ("created", 0.4)):
            if (dt := pdf_dates.get(key)) and dt.date() <= tomorrow:
                info.published_at = dt.date()
                picks.append((f"pdf_meta:{key}", conf))
                break

    if picks:
        info.method, info.confidence = max(picks, key=lambda p: p[1])
    return info


def _htmldate(html: str, today: date) -> date | None:
    try:
        from htmldate import find_date

        found = find_date(
            html,
            original_date=False,
            extensive_search=True,
            outputformat="%Y-%m-%d",
            max_date=today.isoformat(),
        )
    except Exception:  # noqa: BLE001 - htmldate is best-effort
        return None
    return date.fromisoformat(found) if found else None
