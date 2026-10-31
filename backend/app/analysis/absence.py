"""Before reporting a term as missing, search every page for its keywords."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.extract.quotecheck import normalize


@dataclass(frozen=True)
class Mention:
    source_id: str
    page_no: int
    keyword: str
    snippet: str


def _pattern(keyword: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in normalize(keyword).text.split()]
    return re.compile(r"\b" + r"[\s\-/]+".join(words) + r"\b")


def find_mentions(
    keywords: Iterable[str],
    sources: Iterable[tuple[str, tuple[str, ...]]],
    *,
    limit: int = 5,
) -> list[Mention]:
    patterns = [(k, _pattern(k)) for k in keywords]
    found: list[Mention] = []
    for source_id, pages in sources:
        for page_no, text in enumerate(pages, start=1):
            norm = normalize(text).text
            for keyword, pattern in patterns:
                m = pattern.search(norm)
                if m:
                    start = max(0, m.start() - 60)
                    found.append(Mention(source_id, page_no, keyword, norm[start : m.end() + 80]))
                    break
            if len(found) >= limit:
                return found
    return found
