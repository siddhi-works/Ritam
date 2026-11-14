from datetime import date
from decimal import Decimal

from app.bills import printed_amount as _printed_amount
from app.bills import printed_date as _date
from app.statements import (
    Charge,
    StatementCharge,
    StatementRead,
    bill_lines,
    check,
    verified_charges,
)

BILL = """TEST USER
12 SAMPLE NAGAR, PUNE 411001
Statement Date 05/03/2026  Payment Due Date 25/03/2026
Payment received 27/03/2026  Total Amount Due 12,450.00  Minimum Amount Due 620.00
02/03/2026 LATE PAYMENT FEE 1,000.00
02/03/2026 IGST @18% 180.00
01/03/2026 ANNUAL FEE 2,500.00
28/02/2026 SWIGGY BANGALORE 450.00
Schedule of charges: Total Interest charged on 20th July 1478.43"""


def test_name_and_address_lines_never_reach_the_ai():
    kept = bill_lines(BILL)
    assert "TEST USER" not in kept and "SAMPLE NAGAR" not in kept
    assert "LATE PAYMENT FEE 1,000.00" in kept and "Total Amount Due" in kept


def test_amounts_only_in_the_schedule_of_charges_are_not_charges():
    read = StatementRead(
        charges=[
            StatementCharge(description="Total Interest", amount="1478.43", kind="finance_charge")
        ]
    )
    assert verified_charges(read, BILL) == ([], 1)


def test_amounts_not_on_the_bill_are_dropped():
    read = StatementRead(
        charges=[
            StatementCharge(
                description="LATE PAYMENT FEE", amount="1,000.00", kind="late_payment_fee"
            ),
            StatementCharge(description="Invented fee", amount="₹ 799", kind="other_charge"),
        ]
    )
    kept, dropped = verified_charges(read, BILL)
    assert [c.amount for c in kept] == [Decimal("1000.00")]
    assert dropped == 1


def test_late_fee_within_three_days_is_flagged():
    charges = [Charge("LATE PAYMENT FEE", Decimal(1000), "late_payment_fee")]
    out = check(charges, due=date(2026, 3, 25), paid=date(2026, 3, 27), terms=None, card=None)
    assert [f.rule for f in out] == ["rbi.late_fee_grace"]
    # Paid more than 3 days late: the fee is allowed, but the person is still told the rule.
    late = check(charges, due=date(2026, 3, 25), paid=date(2026, 3, 30), terms=None, card=None)
    assert [f.rule for f in late] == ["rbi.late_fee_check"]


def test_payment_before_the_next_due_date_is_not_called_a_bad_late_fee():
    # Last month's payment vs this bill's (next) due date must not raise the strong finding.
    charges = [Charge("LATE PAYMENT FEE", Decimal(1000), "late_payment_fee")]
    out = check(charges, due=date(2026, 10, 25), paid=date(2026, 9, 27), terms=None, card=None)
    assert [f.rule for f in out] == ["rbi.late_fee_check"]


def test_gst_above_18_percent_is_flagged_but_18_is_fine():
    fee = Charge("FINANCE CHARGES", Decimal(1000), "finance_charge")
    ok = check(
        [fee, Charge("GST", Decimal(180), "gst")], due=None, paid=None, terms=None, card=None
    )
    high = check(
        [fee, Charge("GST", Decimal(280), "gst")], due=None, paid=None, terms=None, card=None
    )
    assert ok == []
    assert [f.rule for f in high] == ["gst.rate"]


def test_charges_are_compared_with_the_card_terms():
    charges = [
        Charge("ANNUAL FEE", Decimal(2500), "annual_fee"),
        Charge("RENT PAYMENT FEE", Decimal(100), "rent_payment_fee"),
    ]
    terms = {"annual_fee": [Decimal(500)], "late_payment_fee": [Decimal(1300)]}
    listed = frozenset({"annual_fee", "late_payment_fee"})  # what the terms PDF mentions
    rules = {
        f.rule
        for f in check(charges, due=None, paid=None, terms=terms, card="Axis ACE", listed=listed)
    }
    assert rules == {"terms.amount_mismatch", "terms.unlisted_charge", "info.annual_fee"}
    # Without a stored report Ritam says nothing about the terms.
    no_terms = check(charges, due=None, paid=None, terms=None, card=None)
    assert {f.rule for f in no_terms} == {"info.annual_fee"}


def test_dates_and_totals_must_be_printed():
    printed = {date(2026, 3, 25), date(2026, 3, 27), date(2026, 3, 5)}
    assert _date("25/03/2026", printed) == date(2026, 3, 25)
    assert _date("26/03/2026", printed) is None
    assert _printed_amount("12,450.00", BILL) == "12,450.00"
    assert _printed_amount("13,000", BILL) is None
    assert _printed_amount("not shown", BILL) is None


async def test_endpoint_sends_only_bill_lines_to_the_ai():
    import io
    from types import SimpleNamespace

    from fastapi import UploadFile

    from app.api.statements import check_statement

    seen: list[str] = []

    class FakeLLM:
        async def generate_structured(self, *, prompt: str, schema, **_):
            seen.append(prompt)
            read = schema(
                total_due="12,450.00",
                charges=[
                    StatementCharge(
                        description="LATE PAYMENT FEE", amount="1,000.00", kind="late_payment_fee"
                    )
                ],
            )
            return SimpleNamespace(data=read)

    state = SimpleNamespace(
        settings=SimpleNamespace(max_upload_bytes=1_000_000, parse_timeout_s=30), llm=FakeLLM()
    )
    request = SimpleNamespace(client=SimpleNamespace(host="test"), app=SimpleNamespace(state=state))
    body = (BILL + "\n" + "\n".join(f"01/03/2026 SHOP {i} 10.00" for i in range(20))).encode()
    file = UploadFile(io.BytesIO(body), filename="bill.txt", headers={"content-type": "text/plain"})
    out = await check_statement(request, None, file, None)  # type: ignore[arg-type]
    assert "TEST USER" not in seen[0] and "SAMPLE NAGAR" not in seen[0]
    assert out["charges"][0]["amount"] == 1000.0
    assert out["total_due"] == "12,450.00"


def test_foreign_bills_are_refused_but_indian_bills_with_dollar_purchases_pass():
    from app.discovery.india import indian_bill as looks_indian

    us = "Bright Lending Credit Card Statement\nCredit limit $ 5,000 New balance $ 203.36\nAPR 19.80%"
    assert not looks_indian(us)
    indian = "Amount (Rs.)\n15/09/2026 STEAM GAMES USD 36.00 3,000.00\nIGST @18% 18.90"
    assert looks_indian(indian)
    assert looks_indian(BILL)


def _rules(charges, **kw):
    base = {"due": None, "paid": None, "terms": None, "card": None}
    return {f.rule: f for f in check(charges, **{**base, **kw})}


def test_overlimit_fee_cites_the_consent_rule():
    out = _rules([Charge("OVERLIMIT FEE", Decimal(600), "overlimit_fee")])
    assert out["rbi.overlimit_consent"].ref.endswith("6(b)(v)")


def test_annual_fee_shows_the_waiver_condition():
    out = _rules(
        [Charge("ANNUAL FEE", Decimal(1000), "annual_fee")],
        waiver="Spend Rs. 1,00,000 in a year before renewal",
    )
    assert "1,00,000" in out["info.annual_fee"].detail


def test_no_cost_emi_with_interest_is_flagged_and_emi_cost_is_info():
    emi = [
        Charge("EMI INTEREST", Decimal(250), "emi_interest"),
        Charge("EMI PROCESSING FEE", Decimal(199), "emi_processing_fee"),
    ]
    out = _rules(emi, text="NO COST EMI - SAMSUNG 3/6")
    assert out["rbi.emi_no_cost"].ask and out["rbi.emi_no_cost"].ref.endswith("6(b)(iii)")
    assert not out["info.emi_cost"].ask and "449.00" in out["info.emi_cost"].detail
    assert "rbi.emi_no_cost" not in _rules(emi, text="EMI ON PURCHASE 3/6")


def test_fuel_surcharge_partly_refunded_is_info():
    out = _rules(
        [Charge("FUEL SURCHARGE", Decimal("11.80"), "fuel_surcharge")],
        credits=[Charge("FUEL SURCHARGE WAIVER", Decimal(10), "fuel_surcharge_waiver")],
    )
    assert not out["info.fuel_gst"].ask and "1.80" in out["info.fuel_gst"].detail


def test_duplicate_purchases_are_found_but_not_different_ones():
    text = """10-OCT-16 RAMRAJ COTTON SALEM IN,[CARD]-17404432 Dr 885.00
10-OCT-16 RAMRAJ COTTON SALEM IN,[CARD]-17404433 Dr 885.00
12-OCT-16 RAMRAJ COTTON SALEM IN,[CARD]-17404462 Dr 1,895.00
13-OCT-16 SWIGGY BANGALORE Dr 450.00
13-OCT-16 SWIGGY BANGALORE REFUND Cr 450.00
20-SEP-16 PREVIOUS STATEMENT OUTSTANDING Dr 14,760.28"""
    out = check([], due=None, paid=None, terms=None, card=None, text=text)
    assert [(f.rule, "Ramraj" in f.detail) for f in out] == [("txn.duplicate", True)]


def test_fuel_gst_on_a_separate_line_counts_and_overlimit_is_raised_once():
    out = _rules(
        [
            Charge("FUEL SURCHARGE", Decimal(20), "fuel_surcharge"),
            Charge("IGST @18% ON FUEL SURCHARGE", Decimal("3.60"), "gst"),
            Charge("OVERLIMIT FEE", Decimal(600), "overlimit_fee"),
        ],
        credits=[Charge("FUEL SURCHARGE WAIVER", Decimal(20), "fuel_surcharge_waiver")],
        terms={"annual_fee": [Decimal(1000)]},
        card="HDFC Millennia",
    )
    assert "3.60" in out["info.fuel_gst"].detail
    assert "rbi.overlimit_consent" in out and "terms.unlisted_charge" not in out


def test_a_purchase_labelled_as_a_fee_is_dropped():
    text = "01/03/2026 SWIGGY BANGALORE 600.00\n02/03/2026 OVERLIMIT FEE 750.00"
    read = StatementRead(
        charges=[
            StatementCharge(description="SWIGGY", amount="600.00", kind="overlimit_fee"),
            StatementCharge(description="OVERLIMIT FEE", amount="750.00", kind="overlimit_fee"),
        ]
    )
    kept, dropped = verified_charges(read, text)
    assert [c.amount for c in kept] == [Decimal("750.00")] and dropped == 1


def test_a_normal_annual_fee_is_a_note_unless_sold_as_lifetime_free():
    fee = [Charge("ANNUAL FEE", Decimal(1000), "annual_fee")]
    note = check(fee, due=None, paid=None, terms=None, card=None)
    assert [(f.rule, f.ask) for f in note] == [("info.annual_fee", False)]
    ltf = check(fee, due=None, paid=None, terms=None, card=None, lifetime_free=True)
    assert [(f.rule, f.ask) for f in ltf] == [("fee.waiver_or_ltf", True)]


def test_unlisted_charge_needs_the_terms_document_itself():
    rent = [Charge("RENT PAYMENT FEE", Decimal(100), "rent_payment_fee")]
    terms = {"annual_fee": [Decimal(500)]}
    # The terms PDF was never read: a gap in Ritam's data, not in the bank's disclosure.
    unread = check(rent, due=None, paid=None, terms=terms, card="Axis ACE", listed=None)
    assert "terms.unlisted_charge" not in {f.rule for f in unread}
    read = check(
        rent, due=None, paid=None, terms=terms, card="Axis ACE", listed=frozenset({"annual_fee"})
    )
    assert "terms.unlisted_charge" in {f.rule for f in read}


def test_refunds_and_cashback_are_not_payments():
    from app.statements import payments_from_text

    text = (
        "20/09/2026 PAYMENT RECEIVED - THANK YOU 12,000.00 Cr\n"
        "21/09/2026 UPI REFUND AMAZON 500.00 Cr\n"
        "22/09/2026 CASHBACK RECEIVED 150.00 Cr"
    )
    assert [a for _, a in payments_from_text(text)] == [Decimal("12000.00")]


def test_gst_check_waits_for_a_complete_bill():
    charges = [Charge("FEE", Decimal(100), "annual_fee"), Charge("GST", Decimal(180), "gst")]
    assert "gst.rate" in {
        f.rule for f in check(charges, due=None, paid=None, terms=None, card=None)
    }
    partial = check(charges, due=None, paid=None, terms=None, card=None, complete=False)
    assert "gst.rate" not in {f.rule for f in partial}
