"""The hand-checked card catalogue and matching a card name written in any words to it."""

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

import yaml
from rapidfuzz import fuzz


@dataclass(frozen=True)
class CatalogueCard:
    id: str
    bank: str
    name: str
    aliases: tuple[str, ...]
    sources: tuple[dict[str, str], ...]
    pack: str = "credit_card"


@lru_cache
def catalogue() -> tuple[CatalogueCard, ...]:
    raw = yaml.safe_load(
        resources.files(__package__).joinpath("catalogue.yaml").read_text(encoding="utf-8")
    )
    return tuple(
        CatalogueCard(
            c["id"], c["bank"], c["name"], tuple(c.get("aliases", [])), tuple(c["sources"]), pack
        )
        for section, pack in (("cards", "credit_card"),)
        for c in raw.get(section) or []
    )


# Words every card or scheme name shares; they must never be what makes two names match
# ("IndusInd Legend credit card" is not "AU LIT credit card").
_GENERIC = {
    "credit", "card", "cards", "bank", "the", "my", "a", "of", "for", "and", "first",
    "small", "finance",
}  # fmt: skip


def _distinctive(text: str) -> list[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
    return [w for w in words if w not in _GENERIC and not w.isdigit()]


def _same_word(a: str, b: str) -> bool:
    # Typos are tolerated only on longer words: "millenia" ~ "millennia", but "lit" != "list".
    return a == b or (min(len(a), len(b)) > 3 and fuzz.ratio(a, b) >= 85)


@lru_cache(maxsize=512)
def match_card(text: str, pack: str = "credit_card") -> CatalogueCard | None:
    """Catalogue entry whose distinctive words all appear in `text`; the most specific alias wins."""
    query = _distinctive(text)
    if not query:
        return None
    best: tuple[int, CatalogueCard] | None = None
    for card in (c for c in catalogue() if c.pack == pack):
        for name in (card.name, *card.aliases):
            words = _distinctive(name)
            if words and all(any(_same_word(w, q) for q in query) for w in words):
                score = sum(len(w) for w in words)
                if best is None or score > best[0]:
                    best = (score, card)
    return best[1] if best else None
