from datetime import date
from decimal import Decimal

from app.cases import (
    LetterItem,
    add_working_days,
    closure_penalty,
    complaint_letter,
    complaint_timeline,
    reminders_ics,
)


def test_timeline_counts_30_days_then_90():
    steps = complaint_timeline(date(2026, 11, 1))
    assert [s.when for s in steps] == [
        date(2026, 11, 1),
        date(2026, 12, 1),
        date(2026, 12, 1),
        date(2027, 3, 1),
    ]


def test_an_early_reply_starts_the_90_days_sooner():
    steps = complaint_timeline(date(2026, 11, 1), replied_on=date(2026, 11, 11))
    assert steps[-1].when == date(2027, 2, 9)
    assert "Not happy" in steps[2].what


def test_working_days_skip_weekends():
    # Friday 6 Nov 2026 + 7 working days = Tuesday 17 Nov
    assert add_working_days(date(2026, 11, 6), 7) == date(2026, 11, 17)


def test_closure_penalty_is_500_per_calendar_day_after_7_working_days():
    p = closure_penalty(date(2026, 11, 6), closed_on=date(2026, 11, 27), today=date(2026, 12, 1))
    assert p.due_by == date(2026, 11, 17) and p.days_late == 10 and p.penalty == Decimal(5000)
    on_time = closure_penalty(
        date(2026, 11, 6), closed_on=date(2026, 11, 16), today=date(2026, 12, 1)
    )
    assert on_time.penalty == 0
    still_open = closure_penalty(date(2026, 11, 6), closed_on=None, today=date(2026, 11, 20))
    assert still_open.days_late == 3


def test_letter_names_the_rule_amount_and_leaves_personal_details_blank():
    text = complaint_letter(
        [
            LetterItem("rbi.overlimit_consent", "OVERLIMIT FEE", Decimal(600), "para 6(b)(v)"),
            LetterItem("fee.waiver_or_ltf", "ANNUAL FEE", Decimal(1000), "para 9(b)(viii)"),
        ],
        card="HDFC Bank Millennia credit card",
        bank="HDFC Bank",
        statement_date=date(2026, 10, 5),
    )
    assert "Grievance Redressal Officer / Principal Nodal Officer, HDFC Bank" in text
    assert "OVERLIMIT FEE of Rs 600.00" in text and "(para 6(b)(v))" in text
    assert "Please reverse Rs 1,600.00" in text
    assert "offer email, SMS or screenshot" in text
    assert "[last 4 digits]" in text and "[Your name]" in text
    assert "05 October 2026" in text


def test_calendar_file_has_one_event_per_step():
    ics = reminders_ics(complaint_timeline(date(2026, 11, 1)), title="HDFC fee", uid_seed="x")
    assert ics.startswith("BEGIN:VCALENDAR") and ics.count("BEGIN:VEVENT") == 4
    assert "DTSTART;VALUE=DATE:20270301" in ics and "\r\n" in ics


async def test_endpoints_work_without_a_database():
    from types import SimpleNamespace

    from app.api.cases import ClosureIn, Item, LetterIn, closure, letter, reminders

    req = SimpleNamespace(client=SimpleNamespace(host="t"), headers={})
    out = await letter(
        req,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        LetterIn(
            findings=[
                Item(rule="txn.duplicate", charge="Swiggy", amount=Decimal(450)),
                Item(rule="info.emi_cost"),  # not something to raise: dropped
            ],
            card="Unknown Card",
            complained_on=date(2026, 11, 1),
        ),
    )
    assert "Swiggy of Rs 450.00" in out["letter"] and "EMI" not in out["letter"]
    assert len(out["timeline"]) == 4

    c = await closure(req, ClosureIn(requested_on=date(2026, 1, 5), closed_on=date(2026, 1, 30)))  # type: ignore[arg-type]
    assert c["penalty"] > 0 and "para 8(a)" in c["letter"]

    r = await reminders(req, complained_on=date.today())  # type: ignore[arg-type]
    assert r.media_type == "text/calendar"


async def test_timeline_endpoint():
    from types import SimpleNamespace

    from app.api.cases import timeline

    req = SimpleNamespace(client=SimpleNamespace(host="tl"), headers={})
    steps = await timeline(req, complained_on=date(2026, 11, 1))  # type: ignore[arg-type]
    assert [s["date"] for s in steps][-1] == "2027-03-01"


def test_a_letter_that_is_not_about_a_bill_does_not_mention_a_statement():
    text = complaint_letter(
        [LetterItem("rbi.unsolicited_card", "A card I never asked for", None, None)],
        card="ICICI Bank Coral credit card",
        bank="ICICI Bank",
        statement_date=None,
    )
    assert "statement" not in text.lower()
    assert "Subject: Complaint about my ICICI Bank Coral credit card" in text
