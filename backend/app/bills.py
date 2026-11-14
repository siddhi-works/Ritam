"""Reading and checking a credit card bill, independent of the web layer. Used by the API, the
accuracy test set (evals) and tests alike, so all three exercise exactly the same code.

Order of work: parse -> India-only check -> mask personal details -> keep only bill lines ->
one AI read -> verify every value against the bill's own text -> deterministic rules."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import partial
from typing import Any, Protocol

from app.discovery.india import NOT_INDIAN_BILL, indian_bill
from app.extract.numbers import numbers_in, numbers_supported
from app.ingest.dates import find_dates
from app.ingest.parse import ParseError, parse
from app.ingest.redact import redact
from app.llm.base import LLMError
from app.regulation import CARD_RULES, card_rule_note
from app.statements import (
    SYSTEM,
    BillFacts,
    Charge,
    StatementFinding,
    StatementRead,
    bill_dates,
    bill_lines,
    check,
    compare,
    payments_from_text,
    printed_number,
    verified_charges,
)

MAX_CHARS = 30_000
_PARSE_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bill-parse")


@dataclass(frozen=True)
class CardTerms:
    """The card's terms as they stood on one bill's date, from the bank's own documents."""

    values: dict[str, list[Decimal]]  # amounts in force that day, per charge kind
    listed: frozenset[str] | None  # charge kinds the terms PDF mentions; None if it wasn't read
    waiver: str | None  # the annual-fee waiver condition, as written
    report_id: str | None  # the public report these come from, for a link


class BillError(Exception):
    """A bill Ritam can't check, with the HTTP status and a message for the person."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class Reader(Protocol):
    async def generate_structured(
        self, *, task: Any, system: str, prompt: str, schema: Any
    ) -> Any: ...


def printed_date(raw: str | None, printed: set[date]) -> date | None:
    """The model's date, only if that date is actually printed on the bill."""
    found = bill_dates(raw or "") or [c.value for c in find_dates(raw or "")]
    return found[0] if found and found[0] in printed else None


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def printed_amount(raw: str | None, text: str) -> str | None:
    return raw if raw and numbers_in(raw) and numbers_supported(raw, text) else None


@dataclass
class Bill:
    read: StatementRead
    text: str
    masked: int
    facts: BillFacts
    dropped: int
    credits: list[Charge]


def bill_text(body: bytes, *, filename: str = "", content_type: str = "") -> tuple[str, int]:
    """Masked bill lines ready for the AI, and how many personal details were hidden."""
    try:
        doc = parse(body, content_type=content_type, filename=filename)
    except ParseError as exc:
        raise BillError(
            422, "Ritam couldn't read this file. Upload the PDF your bank emailed you."
        ) from exc
    raw = "\n".join(p.text for p in doc.pages)
    if not indian_bill(raw):
        raise BillError(422, NOT_INDIAN_BILL)
    # Only dated/amount/charge lines go further: name and address lines are dropped here.
    text, masked = redact(raw)
    text = bill_lines(text)
    if len(text.strip()) < 200:
        raise BillError(
            422, "This PDF has no readable text. It may be a scanned image or password-protected."
        )
    return text, sum(masked.values())


def prompt_for(text: str) -> str:
    return f"<statement>\n{text[:MAX_CHARS]}\n</statement>"


def facts_from(read: StatementRead, text: str, masked: int) -> Bill:
    """Everything the model said, kept only where the bill's own text confirms it."""
    charges, dropped = verified_charges(read, text)
    credits, _ = verified_charges(read, text, read.credits)
    printed = set(bill_dates(text)) | {d.value for d in find_dates(text)}
    facts = BillFacts(
        statement_date=printed_date(read.statement_date, printed),
        due=printed_date(read.payment_due_date, printed),
        paid=printed_date(read.payment_received_date, printed),
        total_due=printed_number(read.total_due, text),
        minimum_due=printed_number(read.minimum_due, text),
        credit_limit=printed_number(read.credit_limit, text),
        payments_total=printed_number(read.payments_total, text),
        points_open=printed_number(read.reward_points_opening, text),
        points_close=printed_number(read.reward_points_closing, text),
        points_expired=printed_number(read.reward_points_expired, text),
        charges=charges,
    )
    # Payment rows are plain data on dated lines: fill gaps from the text itself. The latest
    # payment date is used, which keeps the late-fee check cautious.
    pays = [
        p
        for p in payments_from_text(text)
        if facts.statement_date is None or p[0] <= facts.statement_date
    ]
    if pays:
        facts.paid = facts.paid or max(d for d, _ in pays)
        if facts.payments_total is None:
            facts.payments_total = sum((a for _, a in pays), Decimal(0))
    return Bill(read, text, masked, facts, dropped, credits)


async def read_bill(
    body: bytes,
    llm: Reader,
    *,
    filename: str = "",
    content_type: str = "",
    max_bytes: int,
    parse_timeout_s: float = 30.0,
) -> Bill:
    if not body:
        raise BillError(422, "The file is empty.")
    if len(body) > max_bytes:
        raise BillError(413, f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
    # PDF parsing is CPU work: run it on the bills' own small pool, so a stuck or hostile file can
    # tie up at most _PARSE_POOL's threads, never the shared pool the rest of the server uses.
    loop = asyncio.get_running_loop()
    work = partial(bill_text, body, filename=filename, content_type=content_type)
    try:
        text, masked = await asyncio.wait_for(
            loop.run_in_executor(_PARSE_POOL, work), parse_timeout_s
        )
    except TimeoutError as exc:
        raise BillError(
            422, "This PDF took too long to read. Try the PDF your bank emailed you."
        ) from exc
    try:
        out = await llm.generate_structured(
            task="extract", system=SYSTEM, prompt=prompt_for(text), schema=StatementRead
        )
    except LLMError as exc:
        raise BillError(
            503, "Ritam's reading service is busy right now. Try again in a few minutes."
        ) from exc
    return facts_from(out.data, text, masked)


def dated_findings(findings: list[StatementFinding], on: date | None) -> None:
    """A bill older than the card rules it is checked against: say so, and don't present the
    finding as settled."""
    note = card_rule_note(on)
    if note is None:
        return
    for x in findings:
        if x.ref and x.ref.startswith(CARD_RULES.name):
            x.label = "uncertain"
            x.detail = f"{x.detail} {note}"


# The two-bill late-fee check judges the fee against the due date it belongs to. When it reaches a
# verdict, the single-bill late-fee findings (which can only guess that date) give way to it.
LATE_FEE_VERDICTS = {"rbi.late_fee_grace", "info.late_fee_allowed"}
SINGLE_BILL_LATE_FEE = {"rbi.late_fee_grace", "rbi.late_fee_check"}


def _bill_findings(
    bill: Bill, card: str | None, terms: CardTerms | None, lifetime_free: bool
) -> list[StatementFinding]:
    f = bill.facts
    return check(
        f.charges,
        due=f.due,
        paid=f.paid,
        terms=terms.values if terms else None,
        listed=terms.listed if terms else None,
        card=card,
        credits=bill.credits,
        text=bill.text,
        waiver=terms.waiver if terms else None,
        lifetime_free=lifetime_free,
        complete=bill.dropped == 0,
    )


def _result(
    bill: Bill, findings: list[StatementFinding], card: str | None, terms: CardTerms | None
) -> dict[str, Any]:
    f = bill.facts
    dated_findings(findings, f.statement_date)
    return {
        "charges": [
            {"description": c.description, "amount": float(c.amount), "kind": c.kind}
            for c in f.charges
        ],
        "dropped": bill.dropped,
        "findings": [x.__dict__ for x in sorted(findings, key=lambda x: -x.severity)],
        "dates": {
            "statement_date": iso(f.statement_date),
            "payment_due_date": iso(f.due),
            "payment_received_date": iso(f.paid),
        },
        "total_due": printed_amount(bill.read.total_due, bill.text),
        "minimum_due": printed_amount(bill.read.minimum_due, bill.text),
        "card": card,
        "report_id": terms.report_id if terms else None,
        "masked": bill.masked,
        "truncated": len(bill.text) > MAX_CHARS,
    }


def check_bill(
    bill: Bill, *, card: str | None, terms: CardTerms | None, lifetime_free: bool = False
) -> dict[str, Any]:
    """The checked bill as the API returns it. `card` is the matched catalogue name, if any."""
    return _result(bill, _bill_findings(bill, card, terms, lifetime_free), card, terms)


def check_pair(
    a: Bill, b: Bill, *, card: str | None, terms: CardTerms | None, lifetime_free: bool = False
) -> dict[str, Any]:
    """Last month's bill and this month's, in either order: everything check_bill finds on the
    newer one, plus the checks that need both."""
    da, db = a.facts.statement_date, b.facts.statement_date
    if da and db and da > db:
        a, b = b, a
    if da and da == db:
        raise BillError(422, "Both files are the same bill. Upload last month's and this month's.")
    findings = _bill_findings(b, card, terms, lifetime_free)
    extra = compare(a.facts, b.facts)
    if {x.rule for x in extra} & LATE_FEE_VERDICTS:
        findings = [x for x in findings if x.rule not in SINGLE_BILL_LATE_FEE]
    out = _result(b, findings + extra, card, terms)
    out["previous"] = {
        "statement_date": iso(a.facts.statement_date),
        "payment_due_date": iso(a.facts.due),
        "total_due": printed_amount(a.read.total_due, a.text),
    }
    return out
