"""Find a model's quote in the source and map it back to page offsets. Fuzzy matches must carry the
same numbers as the span they matched."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.extract.numbers import ascii_digits, numbers_supported
from app.ingest.parse import PAGE_SEP, Page

MIN_QUOTE_CHARS = 12
DEFAULT_THRESHOLD = 92.0

_CHAR_MAP = str.maketrans(
    {
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
        "‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"',
        "­": None, "​": None, "‌": None, "‍": None, "﻿": None,
    }
)  # fmt: skip
_RUPEE = re.compile(r"(?:\brs\.?|\binr\.?|₹)\s*(?=\d)")


@dataclass(frozen=True)
class Normalized:
    text: str
    index: list[int]  # index[i] = offset in the original string of normalised char i


def normalize(text: str) -> Normalized:
    chars: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, c in enumerate(ascii_digits(text)):
        for n in unicodedata.normalize("NFKC", c).casefold().translate(_CHAR_MAP):
            if n.isspace():
                if prev_space:
                    continue
                n, prev_space = " ", True
            else:
                prev_space = False
            chars.append(n)
            index.append(i)
    while chars and chars[-1] == " ":
        chars.pop()
        index.pop()
    return _sub(Normalized("".join(chars), index), _RUPEE, "₹")


def _sub(norm: Normalized, pattern: re.Pattern[str], repl: str) -> Normalized:
    out: list[str] = []
    index: list[int] = []
    last = 0
    for m in pattern.finditer(norm.text):
        out.append(norm.text[last : m.start()])
        index.extend(norm.index[last : m.start()])
        out.append(repl)
        index.extend([norm.index[m.start()]] * len(repl))
        last = m.end()
    out.append(norm.text[last:])
    index.extend(norm.index[last:])
    return Normalized("".join(out), index)


@dataclass(frozen=True)
class QuoteMatch:
    page_no: int
    char_start: int  # offsets within the page text
    char_end: int
    score: float
    method: str  # exact | fuzzy


class QuoteLocator:
    """Built once per source; locates many quotes against it."""

    def __init__(self, pages: Sequence[Page], threshold: float = DEFAULT_THRESHOLD):
        self._pages = list(pages)
        self._doc = PAGE_SEP.join(p.text for p in self._pages)
        self._norm = normalize(self._doc)
        self._threshold = threshold

    def page_text(self, page_no: int) -> str:
        return next(p.text for p in self._pages if p.page_no == page_no)

    def locate(self, quote: str) -> QuoteMatch | None:
        q = normalize(quote).text.strip(" \"'")
        if len(q) < MIN_QUOTE_CHARS:
            return None
        hay = self._norm.text
        start = hay.find(q)
        if start >= 0:
            return self._to_page(start, start + len(q), 100.0, "exact")

        result = fuzz.partial_ratio_alignment(q, hay, score_cutoff=self._threshold)
        if result is None:
            return None
        span = hay[result.dest_start : result.dest_end]
        if not numbers_supported(q, span):
            return None
        return self._to_page(result.dest_start, result.dest_end, result.score, "fuzzy")

    def _to_page(self, nstart: int, nend: int, score: float, method: str) -> QuoteMatch | None:
        if nend <= nstart:
            return None
        ostart = self._norm.index[nstart]
        oend = self._norm.index[nend - 1] + 1
        for page in reversed(self._pages):
            if page.char_start <= ostart:
                page_end = page.char_start + len(page.text)
                if ostart >= page_end:  # landed in the separator between pages
                    return None
                return QuoteMatch(
                    page_no=page.page_no,
                    char_start=ostart - page.char_start,
                    char_end=min(oend, page_end) - page.char_start,
                    score=round(float(score), 1),
                    method=method,
                )
        return None
