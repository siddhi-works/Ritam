"""Dated RBI rules. A finding cites the rule that was in force on the date that matters (the bill's
date, the complaint's date), not today's rule. Sources:

- Master Direction on Credit Card and Debit Card (Issuance and Conduct), 2022: in force from
  1 July 2022 (para 1(b)); text as updated on 7 March 2024.
- Reserve Bank Integrated Ombudsman Scheme, 2021: from 12 November 2021. A complaint may go to the
  Ombudsman 30 days after complaining to the bank, and within one year of the bank's reply (one
  year and 30 days if it never replied).
- Reserve Bank Integrated Ombudsman Scheme, 2026: from 1 July 2026, replacing the 2021 scheme for
  new complaints. Wait 30 days for the bank, then complain within 90 days (bank-published summary;
  RBI's own text not yet checked by Ritam)."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Regulation:
    key: str
    name: str
    start: date
    end: date | None = None  # last day in force

    def cite(self, para: str) -> str:
        return f"{self.name}, para {para}"

    def in_force(self, on: date) -> bool:
        return self.start <= on and (self.end is None or on <= self.end)


CARD_RULES = Regulation("md2022", "RBI Master Direction on credit cards, 2022", date(2022, 7, 1))


@dataclass(frozen=True)
class OmbudsmanScheme(Regulation):
    file_within_days: int = 90  # after the bank's reply, or after the wait if it never replied
    checked: bool = False  # window confirmed in the scheme text (not just a summary)


OMBUDSMAN = (
    OmbudsmanScheme(
        "rbios2021",
        "Reserve Bank Integrated Ombudsman Scheme, 2021",
        date(2021, 11, 12),
        end=date(2026, 6, 30),
        file_within_days=365,
    ),
    OmbudsmanScheme(
        "rbios2026",
        "Reserve Bank Integrated Ombudsman Scheme, 2026",
        date(2026, 7, 1),
        file_within_days=90,
        checked=True,  # bank-published summary of the scheme
    ),
)


def ombudsman_on(day: date) -> OmbudsmanScheme:
    """The scheme a complaint filed with RBI on `day` falls under (the newest one for later dates)."""
    for s in OMBUDSMAN:
        if s.in_force(day):
            return s
    return OMBUDSMAN[0] if day < OMBUDSMAN[0].start else OMBUDSMAN[-1]


def card_rule_note(on: date | None) -> str | None:
    """A caution when a bill predates the card rules it is checked against, else None."""
    if on is None or CARD_RULES.in_force(on):
        return None
    return (
        f"This bill is from {on:%B %Y}, before these RBI rules took effect on "
        f"{CARD_RULES.start:%d %B %Y}, so they may not apply to it."
    )
