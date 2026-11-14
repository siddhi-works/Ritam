"""India-only guardrail. Ritam judges cards against RBI's rules, so a report on a card issued
abroad, or a bill priced in another currency, would be wrong. Every check here is deterministic
and runs before any AI call."""

import re
from collections.abc import Iterable

from app.discovery.cards import match_card
from app.discovery.domains import AGGREGATOR_DOMAINS, NEWS_DOMAINS, classify, host, matches

NOT_INDIAN = (
    "Ritam only checks credit cards issued in India, against RBI's rules. "
    "This card looks like it is from a bank outside India, so Ritam can't report on it."
)
NOT_INDIAN_BILL = (
    "This looks like a bill from outside India (amounts in dollars, pounds or euros). "
    "Ritam checks Indian credit card bills against RBI's rules, so it can't check this one."
)

# Issuers with no Indian credit cards. Names alone; Indian cards never carry these words.
_FOREIGN_ISSUERS = re.compile(
    r"\b(chase|capital one|discover it|barclaycard|wells fargo|bank of america|synchrony|"
    r"us bank|u\.s\. bank|navy federal|monzo|revolut|amex (us|uk|canada|australia)|"
    r"td bank|rbc|scotiabank|commonwealth bank|westpac|anz)\b",
    re.I,
)
_RUPEE = re.compile(
    r"₹|\bRs\.?\s?\d|\bRs\b|\bINR\b|\brupees?\b|\bGST\b|\bRBI\b|\blakh\b|\.bank\.in\b", re.I
)
_FOREIGN_MONEY = re.compile(r"[$£€]\s?\d|\b(USD|GBP|EUR|AUD|CAD)\b|\bAPR\b")
# Issuer sites go through classify, which knows their India-only paths.
_INDIAN_SITES = AGGREGATOR_DOMAINS | NEWS_DOMAINS


def foreign_issuer(product: str | None) -> bool:
    """The name itself says the card is from abroad (and it is not on Ritam's Indian list)."""
    return bool(product and _FOREIGN_ISSUERS.search(product) and not match_card(product))


def indian_site(url: str) -> bool:
    h = host(url)
    return classify(url)[1] or h.endswith(".in") or matches(h, _INDIAN_SITES)


def indian_text(text: str) -> bool:
    """For a card's documents: rupee or Indian-regulation markers outweigh foreign currency."""
    return len(_RUPEE.findall(text)) >= max(1, len(_FOREIGN_MONEY.findall(text)) // 3)


def indian_bill(text: str) -> bool:
    """For a bill: any Indian marker, or hardly any foreign currency. An Indian bill may carry a
    purchase in dollars; a foreign bill has prices in dollars throughout."""
    return bool(_RUPEE.search(text)) or len(_FOREIGN_MONEY.findall(text)) < 2


def card_origin(product: str | None, urls: Iterable[str]) -> bool | None:
    """True or False when the card's name or sources settle it, None when only the documents'
    text can tell (so callers load the text only then)."""
    if foreign_issuer(product):
        return False
    if (product and match_card(product)) or any(classify(u)[1] for u in urls):
        return True
    return None


def looks_indian_card(product: str | None, urls: Iterable[str], texts: Iterable[str]) -> bool:
    """True when anything shows the card is Indian: on the checked list, an official Indian
    source (bank, RBI, government), or rupee/RBI markers in what was read."""
    origin = card_origin(product, urls)
    return origin if origin is not None else any(indian_text(t) for t in texts)
