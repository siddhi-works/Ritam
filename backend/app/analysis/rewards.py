"""How a card's rewards actually reach the cardholder. A card sold as "cashback" may pay in
vouchers, points or a wallet balance; points are worth whatever the bank says one point is."""

import re
from dataclasses import dataclass
from typing import Literal

RewardForm = Literal["money", "points", "vouchers", "wallet", "miles"]

FORM_NAMES: dict[RewardForm, str] = {
    "money": "money credited to your card bill",
    "points": "reward points",
    "vouchers": "vouchers or gift cards",
    "wallet": "a wallet balance",
    "miles": "air miles",
}

_FORMS: list[tuple[RewardForm, re.Pattern[str]]] = [
    ("money", re.compile(r"statement credit|credited (?:back )?(?:to|in|into) (?:your |the )?(?:card|credit card|card account|statement|bill)|credit to (?:your |the )?card account|reduces? (?:your|the) (?:bill|outstanding)", re.I)),
    ("vouchers", re.compile(r"\bvouchers?\b|gift ?cards?|e-?gift", re.I)),
    ("wallet", re.compile(r"amazon pay balance|\bwallet\b|paytm balance|neucoins?|supercoins?", re.I)),
    ("miles", re.compile(r"air ?miles|\bmiles\b|airline (?:points|partner)", re.I)),
    ("points", re.compile(r"reward points?|\bpoints?\b|\brps?\b", re.I)),
]  # fmt: skip

CASHBACK = re.compile(r"cash ?back", re.I)

# "4 reward points per Rs 150", "2 RP for every ₹100 spent"
_RATE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:x\s*)?(?:reward\s*)?(?:points?|rps?|neucoins?|miles)\s*"
    r"(?:per|for every|on every|on each|for each)\s*(?:rs\.?|₹|inr)?\s*([\d,]+)",
    re.I,
)


def reward_forms(text: str) -> set[RewardForm]:
    """Every form the text says rewards come in. Points named only as the unit of a voucher or
    wallet scheme still count: the cardholder still has to redeem them."""
    return {form for form, pattern in _FORMS if pattern.search(text)}


@dataclass(frozen=True)
class PointsRate:
    points: float
    per_rupees: float

    def percent(self, point_value: float) -> float:
        """What the rewards are worth, as a percentage of what you spend."""
        return self.points * point_value / self.per_rupees * 100


def points_rate(text: str) -> PointsRate | None:
    m = _RATE.search(text)
    if not m:
        return None
    per = float(m.group(2).replace(",", ""))
    return PointsRate(float(m.group(1)), per) if per > 0 else None


_AFTER_EQUALS = re.compile(
    r"(?:=|worth|value of|equals?)\s*(?:rs\.?|₹|inr|re\.?)?\s*(\d+(?:\.\d+)?)\s*(paise|p\b)?", re.I
)
_RUPEES = re.compile(r"(?:rs\.?|₹|inr|re\.?)\s*(\d+(?:\.\d+)?)", re.I)
_PAISE = re.compile(r"(\d+(?:\.\d+)?)\s*paise", re.I)


def rupees_per_point(text: str) -> float | None:
    """One point's value from "1 RP = Rs 0.25", "worth 25 paise", "Rs 0.20 per point"; None when
    the text gives no clear value or one too large to be a single point (over Rs 5)."""
    value: float | None = None
    if m := _AFTER_EQUALS.search(text):
        value = float(m.group(1)) / (100 if m.group(2) else 1)
    elif m := _PAISE.search(text):
        value = float(m.group(1)) / 100
    elif m := _RUPEES.search(text):
        value = float(m.group(1))
    return value if value is not None and 0 < value <= 5 else None
