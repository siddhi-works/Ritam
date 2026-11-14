from datetime import date
from decimal import Decimal

from app.statements import BillFacts, Charge, compare, consecutive, printed_number


def _bill(**kw) -> BillFacts:
    base = dict(
        statement_date=None, due=None, paid=None, total_due=None, minimum_due=None,
        credit_limit=None, payments_total=None, points_open=None, points_close=None,
        points_expired=None, charges=[],
    )  # fmt: skip
    return BillFacts(**{**base, **kw})


PREV = dict(statement_date=date(2026, 9, 5), due=date(2026, 9, 25), total_due=Decimal(12000),
            minimum_due=Decimal(600))  # fmt: skip
LATE = Charge("LATE PAYMENT FEE", Decimal(600), "late_payment_fee")
INTEREST = Charge("FINANCE CHARGES", Decimal(412), "finance_charge")


def _rules(prev, cur):
    return {f.rule: f for f in compare(prev, cur)}


def test_late_fee_is_judged_against_last_bills_due_date():
    cur = dict(
        statement_date=date(2026, 10, 5), due=date(2026, 10, 25), payments_total=Decimal(12000)
    )
    on_time = _rules(_bill(**PREV), _bill(**cur, paid=date(2026, 9, 27), charges=[LATE]))
    assert on_time["rbi.late_fee_grace"].ref.endswith("9(b)(v)")
    too_late = _rules(_bill(**PREV), _bill(**cur, paid=date(2026, 9, 30), charges=[LATE]))
    assert "rbi.late_fee_grace" not in too_late and not too_late["info.late_fee_allowed"].ask


def test_paying_less_than_the_minimum_does_not_make_the_late_fee_wrong():
    cur = _bill(statement_date=date(2026, 10, 5), paid=date(2026, 9, 24), payments_total=Decimal(100),
                charges=[LATE])  # fmt: skip
    assert "rbi.late_fee_grace" not in _rules(_bill(**PREV), cur)


def test_interest_after_paying_in_full_on_time():
    cur = dict(
        statement_date=date(2026, 10, 5), paid=date(2026, 9, 20), payments_total=Decimal(12000)
    )
    out = _rules(_bill(**PREV), _bill(**cur, charges=[INTEREST]))
    assert out["rbi.interest_after_full_payment"].ref.endswith("9(b)(vi)")
    # Not when the previous bill was itself revolving, or cash was withdrawn, or paid short/late.
    revolving = _bill(**PREV, charges=[INTEREST])
    assert "rbi.interest_after_full_payment" not in _rules(
        revolving, _bill(**cur, charges=[INTEREST])
    )
    cash = [INTEREST, Charge("CASH ADV FEE", Decimal(500), "cash_advance_fee")]
    assert "rbi.interest_after_full_payment" not in _rules(
        _bill(**PREV), _bill(**cur, charges=cash)
    )
    short = {**cur, "payments_total": Decimal(11000)}
    assert "rbi.interest_after_full_payment" not in _rules(
        _bill(**PREV), _bill(**short, charges=[INTEREST])
    )


def test_limit_cut_and_missing_points():
    prev = _bill(**PREV, credit_limit=Decimal(200000), points_close=Decimal(15000))
    cur = _bill(statement_date=date(2026, 10, 5), credit_limit=Decimal(20000), points_open=Decimal(0),
                points_expired=Decimal(1200),
                charges=[Charge("OVERLIMIT FEE", Decimal(600), "overlimit_fee")])  # fmt: skip
    out = _rules(prev, cur)
    assert (
        out["rbi.limit_cut_notice"].severity == 4
        and "over-limit" in out["rbi.limit_cut_notice"].detail
    )
    assert "15,000 points" in out["points.missing"].detail
    assert not out["info.points_expired"].ask


def test_bills_months_apart_skip_the_date_checks():
    cur = _bill(statement_date=date(2026, 12, 5), paid=date(2026, 9, 27), payments_total=Decimal(12000),
                charges=[LATE, INTEREST])  # fmt: skip
    out = _rules(_bill(**PREV), cur)
    assert set(out) == {"info.not_consecutive"}
    assert consecutive(_bill(**PREV), _bill(statement_date=date(2026, 10, 5)))


def test_printed_number_needs_every_number_on_the_bill():
    text = "Credit Limit 1,50,000 Available 1,20,000"
    assert printed_number("1,50,000", text) == Decimal(150000)
    assert printed_number("2,00,000", text) is None and printed_number(None, text) is None


async def test_compare_endpoint_orders_bills_and_replaces_the_vague_late_fee_note():
    import io
    from types import SimpleNamespace

    from fastapi import UploadFile

    from app.api.statements import compare_statements
    from app.statements import StatementCharge, StatementRead

    lines = "\n".join(f"0{i}/10/2026 SHOP {i} 10.00" for i in range(1, 9))
    sep = (
        "Statement Date 05/09/2026 Payment Due Date 25/09/2026 Total Amount Due 12,000.00 Minimum 600.00\n"
        + lines
    )
    octb = ("Statement Date 05/10/2026 Payment Due Date 25/10/2026 Payments 12,000.00\n"
            "27/09/2026 PAYMENT RECEIVED 12,000.00 Cr\n26/09/2026 LATE PAYMENT FEE 600.00\n" + lines)  # fmt: skip
    reads = {
        "Statement Date 05/09": StatementRead(statement_date="05/09/2026", payment_due_date="25/09/2026",
                                              total_due="12,000.00", minimum_due="600.00"),
        "Statement Date 05/10": StatementRead(
            statement_date="05/10/2026", payment_due_date="25/10/2026", payment_received_date="27/09/2026",
            payments_total="12,000.00",
            charges=[StatementCharge(description="LATE PAYMENT FEE", amount="600.00", kind="late_payment_fee")],
        ),
    }  # fmt: skip

    class FakeLLM:
        async def generate_structured(self, *, prompt, **_):
            return SimpleNamespace(data=next(r for k, r in reads.items() if k in prompt))

    state = SimpleNamespace(
        settings=SimpleNamespace(max_upload_bytes=1_000_000, parse_timeout_s=30), llm=FakeLLM()
    )
    req = SimpleNamespace(client=SimpleNamespace(host="cmp"), app=SimpleNamespace(state=state))

    def up(t):
        return UploadFile(
            io.BytesIO(t.encode()), filename="b.txt", headers={"content-type": "text/plain"}
        )

    # Uploaded the wrong way round on purpose.
    out = await compare_statements(req, None, up(octb), up(sep), None)  # type: ignore[arg-type]
    rules = [f["rule"] for f in out["findings"]]
    assert "rbi.late_fee_grace" in rules and "rbi.late_fee_check" not in rules
    assert out["previous"]["statement_date"] == "2026-09-05"
