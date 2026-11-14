"""Case file: turn findings into a complaint the bank must answer, with the RBI escalation dates.
Everything here is deterministic; no AI writes or decides any part of it. Nothing is stored:
the caller keeps the result.

Rules used (RBI Master Direction on credit cards, 2022, updated 7 March 2024):
  8(a)   card closure within 7 working days, else Rs 500 per calendar day of delay
  6(a)(iv) unsolicited card or upgrade: charges reversed plus a penalty of twice their value
Integrated Ombudsman Scheme 2026 (in force 1 July 2026; bank-published summary): approach the bank
first, wait 30 days for its reply, then complain to the RBI Ombudsman within 90 days."""

import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.regulation import CARD_RULES, ombudsman_on
from app.statements import RBI_LATE_GRACE_DAYS as GRACE

BANK_REPLY_DAYS = 30  # the same under the 2021 and 2026 Ombudsman schemes
CLOSURE_WORKING_DAYS = 7
CLOSURE_PENALTY_PER_DAY = Decimal(500)


@dataclass(frozen=True)
class Step:
    when: date
    what: str
    why: str


def complaint_timeline(complained_on: date, replied_on: date | None = None) -> list[Step]:
    """When the bank must reply, when RBI can be approached, and the last day to do so, under the
    Ombudsman scheme in force when the RBI complaint can first be made. The window is counted from
    the bank's reply when there is one (the earlier, safer reading), otherwise from the end of the
    wait."""
    reply_due = complained_on + timedelta(days=BANK_REPLY_DAYS)
    start = replied_on if replied_on and replied_on < reply_due else reply_due
    scheme = ombudsman_on(start)
    return [
        Step(
            complained_on,
            "You complained to the bank",
            "Keep the complaint number and a copy of what you sent.",
        ),
        Step(
            reply_due,
            "The bank should have replied by now",
            f"Banks get {BANK_REPLY_DAYS} days to resolve a complaint before you can go to RBI.",
        ),
        Step(
            start,
            "You can complain to the RBI Ombudsman from today"
            if not replied_on
            else "Not happy with the bank's reply? You can complain to the RBI Ombudsman",
            "At cms.rbi.org.in or by calling 14448. It is free.",
        ),
        Step(
            start + timedelta(days=scheme.file_within_days),
            "Last day to complain to the RBI Ombudsman",
            f"After this, RBI may not take up the complaint ({scheme.name})."
            + (
                ""
                if scheme.checked
                else " Ritam hasn't yet confirmed this window in RBI's own text."
            ),
        ),
    ]


def add_working_days(start: date, days: int) -> date:
    """Monday to Friday only. Bank holidays are not known here, so the result can be a day or
    two early; the text says so."""
    d = start
    while days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days -= 1
    return d


@dataclass(frozen=True)
class ClosurePenalty:
    requested_on: date
    due_by: date
    closed_on: date | None
    days_late: int
    penalty: Decimal

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["penalty"] = float(self.penalty)
        return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in d.items()}


def closure_penalty(requested_on: date, closed_on: date | None, today: date) -> ClosurePenalty:
    """Rs 500 for every calendar day after the 7th working day until the card is closed
    (or until today, if it still isn't). Applies only when nothing was owed on the card."""
    due_by = add_working_days(requested_on, CLOSURE_WORKING_DAYS)
    end = closed_on or today
    late = max(0, (end - due_by).days)
    return ClosurePenalty(requested_on, due_by, closed_on, late, CLOSURE_PENALTY_PER_DAY * late)


# The rule each finding rests on. Decided here, never taken from the request, so a letter can only
# cite a paragraph Ritam actually relies on.
REFS: dict[str, str] = {
    "rbi.late_fee_grace": CARD_RULES.cite("9(b)(v)"),
    "rbi.late_fee_check": CARD_RULES.cite("9(b)(v)"),
    "rbi.overlimit_consent": CARD_RULES.cite("6(b)(v)"),
    "fee.waiver_or_ltf": CARD_RULES.cite("9(b)(viii)"),
    "rbi.emi_no_cost": CARD_RULES.cite("6(b)(iii)"),
    "txn.duplicate": CARD_RULES.cite("10(b)"),
    "rbi.unsolicited_card": CARD_RULES.cite("6(a)(iv)"),
    "rbi.interest_after_full_payment": CARD_RULES.cite("9(b)(vi)"),
    "rbi.limit_cut_notice": CARD_RULES.cite("11(b)"),
    "rbi.closure_delay": CARD_RULES.cite("8(a)"),
}

NOT_ABOUT_A_BILL = {"rbi.unsolicited_card", "rbi.closure_delay"}

# One plain sentence per finding rule: why the bank should reverse it.
REASONS: dict[str, str] = {
    "rbi.late_fee_grace": f"I paid within {GRACE} days of the due date. A late fee may be charged "
    f"only when a bill is past due for more than {GRACE} days",
    "rbi.late_fee_check": "Please confirm the payment due date this fee relates to and when my "
    f"payment was received. A late fee may be charged only when a bill is past due for more than "
    f"{GRACE} days",
    "rbi.overlimit_consent": "I did not give consent to go over my credit limit. An over-limit fee "
    "may not be charged without the cardholder's explicit consent",
    "fee.waiver_or_ltf": "This fee should not apply to my card: I met the fee-waiver condition, or "
    "the card was offered to me as lifetime free",
    "rbi.emi_no_cost": "This EMI was offered as no-cost but interest has been charged on it without "
    "an equal discount shown on my statement",
    "txn.duplicate": "I made this purchase once but have been charged more than once",
    "terms.unlisted_charge": "I cannot find this charge in the card's terms. A charge that was not "
    "disclosed to me may not be levied without my consent",
    "terms.amount_mismatch": "The amount differs from the fee stated in the card's terms",
    "gst.rate": "The GST charged is more than 18% of the fees and interest it applies to",
    "rbi.unsolicited_card": "I never asked for this card or upgrade. Charges on an unsolicited card "
    "must be reversed, and the bank must pay a penalty of twice their value",
    "rbi.interest_after_full_payment": "I paid the whole previous bill by its due date, yet interest "
    "was charged. Interest may be charged only on what is still owed after my payments",
    "rbi.limit_cut_notice": "My credit limit was reduced without the notice the bank must give",
    "rbi.closure_delay": "I asked for my card to be closed and nothing was owed, but it was not "
    f"closed within {CLOSURE_WORKING_DAYS} working days",
}


@dataclass(frozen=True)
class LetterItem:
    rule: str
    charge: str | None
    amount: Decimal | None
    ref: str | None


def _short(card: str | None) -> str:
    """ "HDFC Bank Millennia credit card" -> "HDFC Bank Millennia", so the letter can say
    "my ... credit card" without repeating it."""
    return re.sub(r"\s+credit card$", "", card, flags=re.I) if card else "[card name]"


def _letter(bank: str | None, subject: str, body: list[str], attached: list[str]) -> str:
    """The parts every letter shares. Personal details are blanks: Ritam never sees them."""
    return "\n".join(
        [
            f"To: The Grievance Redressal Officer / Principal Nodal Officer, {bank or '[bank name]'}",
            "",
            f"Subject: {subject}",
            "",
            "Dear Sir or Madam,",
            "",
            *body,
            "",
            f"If this is not resolved within {BANK_REPLY_DAYS} days, I will approach the RBI "
            "Ombudsman under the Reserve Bank Integrated Ombudsman Scheme.",
            "",
            "Attached: " + "; ".join(attached) + ".",
            "",
            "Yours faithfully,",
            "[Your name]",
            "[Registered mobile number]",
            "[Date]",
        ]
    )


def closure_letter(p: ClosurePenalty, *, card: str | None, bank: str | None) -> str:
    """Claim for a card not closed within the closure deadline (para 8(a))."""
    name = _short(card)
    until = f"It was closed on {p.closed_on:%d %B %Y}" if p.closed_on else "It is still not closed"
    return _letter(
        bank,
        f"{name} credit card not closed within {CLOSURE_WORKING_DAYS} working days: "
        "compensation due",
        [
            f"I asked for my {name} credit card ending [last 4 digits] to be closed on "
            f"{p.requested_on:%d %B %Y}, through [email / app / customer care, with request "
            "number]. Nothing was owed on the card.",
            "",
            f"Under the {CARD_RULES.cite('8(a)')}, a closure request must be completed within "
            f"{CLOSURE_WORKING_DAYS} working days, that is by {p.due_by:%d %B %Y}, and the bank "
            f"must pay Rs {CLOSURE_PENALTY_PER_DAY:,.0f} for each calendar day of delay. {until}: "
            f"{p.days_late} days late, so at least Rs {p.penalty:,.0f} is due to me (bank "
            "holidays would add to it).",
            "",
            "Please close the card if it is still open, pay this amount to my account, reverse any "
            "fee or interest charged after my request, and confirm that the closure has been "
            "reported to the credit bureaus.",
        ],
        ["my closure request and any reply from the bank"],
    )


def complaint_letter(
    items: list[LetterItem],
    *,
    card: str | None,
    bank: str | None,
    statement_date: date | None,
    report_link: str | None = None,
    extra: str | None = None,
) -> str:
    """A complaint about charges on a statement, one numbered point per finding."""
    name = _short(card)
    on = f" dated {statement_date:%d %B %Y}" if statement_date else ""
    # Complaints like an unsolicited card aren't about a statement at all.
    about_bill = statement_date is not None or any(it.rule not in NOT_ABOUT_A_BILL for it in items)
    points = [
        f"{n}. {it.charge or 'Charge'}{f' of Rs {it.amount:,.2f}' if it.amount else ''}: "
        f"{REASONS.get(it.rule, 'Please explain this charge')}{f' ({it.ref})' if it.ref else ''}."
        for n, it in enumerate(items, 1)
    ]
    total = sum((it.amount or Decimal(0) for it in items), Decimal(0))
    body = [
        f"I hold the {name} credit card ending [last 4 digits]. "
        + (
            f"On my statement{on}, I am disputing the following:"
            if about_bill
            else "I am raising the following:"
        ),
        "",
        *points,
        "",
        f"Please reverse {f'Rs {total:,.2f}' if total else 'these amounts'}, together with the GST "
        "and any interest charged on them, and confirm in writing. Please also make sure no late "
        "fee or adverse credit report results from these amounts while this complaint is open.",
    ]
    if extra:
        body += ["", extra.strip()[:1000]]
    attached = (
        ["a copy of the statement"] if about_bill else ["any letter or message about the card"]
    )
    if any(it.rule == "fee.waiver_or_ltf" for it in items):
        attached.append(
            "the offer email, SMS or screenshot showing the card was free or the waiver condition"
        )
    if report_link:
        attached.append(f"the card's terms as checked by Ritam: {report_link}")
    return _letter(
        bank,
        f"Complaint about charges on my {name} credit card statement{on}"
        if about_bill
        else f"Complaint about my {name} credit card",
        body,
        attached,
    )


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def reminders_ics(steps: list[Step], *, title: str, uid_seed: str) -> str:
    """An all-day calendar event per future step. Works with Google, Apple and Outlook calendars;
    no account or email needed."""
    out = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Ritam//Complaint dates//EN",
        "CALSCALE:GREGORIAN",
    ]
    made = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")  # when this file was created
    for i, s in enumerate(steps):
        day = s.when.strftime("%Y%m%d")
        nxt = (s.when + timedelta(days=1)).strftime("%Y%m%d")
        out += [
            "BEGIN:VEVENT",
            f"UID:ritam-{uid_seed}-{i}@ritam",
            f"DTSTAMP:{made}",
            f"DTSTART;VALUE=DATE:{day}",
            f"DTEND;VALUE=DATE:{nxt}",
            f"SUMMARY:{_ics_escape(f'{title}: {s.what}')}",
            f"DESCRIPTION:{_ics_escape(s.why)}",
            "BEGIN:VALARM",
            "TRIGGER:-PT9H",  # 3 pm the day before
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_ics_escape(s.what)}",
            "END:VALARM",
            "END:VEVENT",
        ]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"
