"""Card finder: what to look for in a credit card, worked out from the person's own spending.

Ritam doesn't name cards here. It turns someone's spending into a checklist (must have, nice to
have, skip if, questions to ask) with the maths behind each point, all in their own rupees and
percentages, so it scales with inflation and never goes out of date. Market figures appear only
as dated benchmarks computed from banks' own documents (app.benchmarks), and are left out when
there isn't enough recent data. Plain rules; no AI."""

from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal["online", "dining", "groceries", "fuel", "travel", "bills", "other"]
CATEGORY_NAMES: dict[str, str] = {
    "online": "online shopping",
    "dining": "food delivery and dining",
    "groceries": "groceries",
    "fuel": "fuel",
    "travel": "travel bookings",
    "bills": "bills and utilities",
    "other": "everything else",
}
# Categories banks often leave out of rewards; worth asking about when they are a big share.
OFTEN_EXCLUDED = {"fuel", "bills"}
MAIN_SHARE = Decimal("0.25")  # a category this big deserves its own reward rate
# Where a brand's spending usually falls, so a co-branded card is weighed against the right share.
APP_CATEGORY: dict[str, Category] = {
    "swiggy": "dining", "zomato": "dining", "eazydiner": "dining",
    "amazon": "online", "flipkart": "online", "myntra": "online", "tata neu": "online", "ajio": "online",
    "makemytrip": "travel", "irctc": "travel", "indigo": "travel", "air india": "travel", "uber": "travel",
    "ola": "travel", "cleartrip": "travel", "yatra": "travel",
    "bpcl": "fuel", "indianoil": "fuel", "indian oil": "fuel", "hpcl": "fuel",
    "bigbasket": "groceries", "blinkit": "groceries", "zepto": "groceries", "dmart": "groceries",
    "airtel": "bills", "jio": "bills",
}  # fmt: skip


class Answers(BaseModel):
    spend: dict[Category, Decimal] = Field(description="rupees per month, by category")
    abroad_per_year: Decimal = Field(default=Decimal(0), ge=0, le=100_000_000)
    lounge_visits_per_year: int = Field(default=0, ge=0, le=200)
    max_fee: Decimal = Field(default=Decimal(0), ge=0, le=100_000)
    pays_in_full: bool = True
    apps: list[str] = Field(default_factory=list, max_length=5)


@dataclass
class Point:
    text: str
    maths: str | None = None
    benchmark: str | None = None  # a dated market figure, when Ritam has enough recent data


@dataclass
class Checklist:
    yearly_spend: int
    must_have: list[Point] = field(default_factory=list)
    nice_to_have: list[Point] = field(default_factory=list)
    skip_if: list[Point] = field(default_factory=list)
    ask_the_bank: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def rupees(v: Decimal | int) -> str:
    """Indian grouping: 240000 -> 2,40,000."""
    n = int(Decimal(v).quantize(Decimal(1), ROUND_HALF_UP))
    s = str(abs(n))
    head, tail = s[:-3], s[-3:]
    while len(head) > 2:
        tail = f"{head[-2:]},{tail}"
        head = head[:-2]
    out = f"{head},{tail}" if head else tail
    return f"₹{'-' if n < 0 else ''}{out}"


def percent(v: Decimal, places: int = 1) -> str:
    step = Decimal(1).scaleb(-places)
    return f"{v.quantize(step, ROUND_HALF_UP).normalize():f}%"


def build(a: Answers, benchmarks: dict[str, str] | None = None) -> Checklist:
    bench = benchmarks or {}
    monthly = {k: v for k, v in a.spend.items() if v > 0}
    yearly = sum(monthly.values(), Decimal(0)) * 12
    c = Checklist(yearly_spend=int(yearly))
    one_percent = yearly / 100

    if not a.pays_in_full:
        c.must_have.append(Point(
            "Pay the full bill every month before choosing for rewards.",
            "Card interest costs far more than any reward: when a balance carries over, interest is "
            "usually charged on the whole bill, and rewards rarely come to more than a few percent.",
            bench.get("finance_charge"),
        ))  # fmt: skip
        c.skip_if.append(Point("Picking a card for its rewards while you carry a balance."))

    if yearly > 0:
        ranked = sorted(monthly.items(), key=lambda kv: -kv[1])
        for cat, amount in ranked:
            share = amount * 12 / yearly
            if share < MAIN_SHARE and cat != ranked[0][0]:
                continue
            name = CATEGORY_NAMES[cat]
            c.must_have.append(Point(
                f"Higher rewards on {name}: it's {percent(share * 100)} of what you spend.",
                f"Every 1% back on {rupees(amount)} a month of {name} is "
                f"{rupees(amount * 12 / 100)} a year.",
            ))  # fmt: skip
            if cat in OFTEN_EXCLUDED:
                c.skip_if.append(Point(f"The card gives no rewards on {name}, your biggest spend."))
            if cat == "fuel":
                c.nice_to_have.append(Point(
                    f"A fuel surcharge waiver that covers fills of at least {rupees(amount)} a month.",
                    "Petrol pumps add a surcharge to card payments; a waiver gives it back, usually "
                    "only within a monthly spend range.",
                    bench.get("fuel_surcharge_waiver"),
                ))  # fmt: skip

        # Fees: what one is worth to this person, and when a waiver is reachable.
        if a.max_fee <= 0:
            c.must_have.append(Point(
                "No annual fee, or a fee waiver you'll reach without changing how you spend.",
                f"You spend about {rupees(yearly)} a year, so a waiver at or below that is free for you.",
                bench.get("annual_fee"),
            ))  # fmt: skip
        else:
            breakeven = a.max_fee / yearly * 100
            c.must_have.append(Point(
                f"An annual fee of at most {rupees(a.max_fee)}, and only if the rewards cover it.",
                f"On your {rupees(yearly)} a year, a {rupees(a.max_fee)} fee pays for itself once the card "
                f"gives at least {percent(breakeven)} back on everything ({rupees(one_percent)} for each 1%).",
                bench.get("annual_fee"),
            ))  # fmt: skip
        c.nice_to_have.append(Point(
            f"A fee waiver at or below {rupees(yearly)} of spend a year.",
            "That's what you spend now, so the fee would be waived without extra spending.",
            bench.get("annual_fee_waiver"),
        ))  # fmt: skip
        c.skip_if.append(Point(
            f"The fee is above {rupees(a.max_fee)} and the waiver needs more than {rupees(yearly)} a year."
            if a.max_fee > 0
            else f"The card has a fee and the waiver needs more than {rupees(yearly)} a year."
        ))  # fmt: skip

    if a.abroad_per_year > 0:
        c.must_have.append(Point(
            "A low foreign currency markup.",
            f"You spend about {rupees(a.abroad_per_year)} a year abroad or on foreign websites: every 1% "
            f"of markup costs you {rupees(a.abroad_per_year / 100)}, plus 18% GST on the markup.",
            bench.get("forex_markup"),
        ))  # fmt: skip
        c.ask_the_bank.append("What is the foreign currency markup, and is GST charged on top?")

    if a.lounge_visits_per_year > 0:
        c.nice_to_have.append(Point(
            f"Airport lounge access with at least {a.lounge_visits_per_year} visits a year.",
            "Many cards now unlock lounge visits only after a set spend in the previous quarter.",
            bench.get("domestic_lounge_visits"),
        ))  # fmt: skip
        c.ask_the_bank.append(
            "Is lounge access free, or does it need a minimum spend in the previous quarter?"
        )

    for app in [x.strip() for x in a.apps if x.strip()][:5]:
        cat = APP_CATEGORY.get(app.lower(), "online")
        share = monthly.get(cat, Decimal(0)) * 12 / yearly if yearly else Decimal(0)
        c.nice_to_have.append(Point(
            f"A card made with {app} (a co-branded card).",
            f"Worth it only if much of your spending is with {app}. {app} usually falls under "
            f"{CATEGORY_NAMES[cat]}, which is {percent(share * 100)} of what you spend.",
        ))  # fmt: skip

    c.ask_the_bank += [
        "Exactly what spend counts towards the fee waiver, and over which 12 months?",
        "Is there a monthly cap on rewards, and which spends earn nothing (rent, wallet loads, fuel, "
        "bills, insurance)?",
        "What is one reward point worth in rupees, and is there a fee to redeem?",
        "Can the bank change the rewards later, and how will it tell me?",
    ]
    return c
