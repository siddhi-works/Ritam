from datetime import date

from app.cases import complaint_timeline
from app.regulation import card_rule_note, ombudsman_on
from app.terms import TermVersion, changes_between, in_force, then_vs_now, timeline


def _v(value, dated, by="effective", amount=None, attr="annual_fee", cid="c"):
    norm = {"type": "money", "parsed": True, "value": amount} if amount is not None else None
    return TermVersion(attr, value, norm, dated if by == "effective" else None, dated, by,
                       "quote", "https://bank.example/mitc.pdf", "MITC", cid)  # fmt: skip


def test_value_in_force_on_a_date_and_repeats_collapse():
    vs = [
        _v("Rs 500", date(2023, 1, 1), amount=500),
        _v("₹500 + GST", date(2024, 1, 1), by="document", amount=500),  # same value restated
        _v("Rs 999", date(2025, 4, 1), amount=999),
    ]
    assert [s.values[0].value for s in timeline(vs)] == ["Rs 500", "Rs 999"]
    assert in_force(vs, date(2024, 6, 1)).values[0].value == "Rs 500"  # type: ignore[union-attr]
    assert in_force(vs, date(2025, 4, 1)).values[0].value == "Rs 999"  # type: ignore[union-attr]
    assert in_force(vs, date(2022, 6, 1)) is None


def test_then_vs_now_and_changes_between():
    by = {
        "annual_fee": [
            _v("Rs 500", date(2023, 1, 1), amount=500),
            _v("Rs 999", date(2025, 4, 1), amount=999),
        ],
        "forex_markup": [_v("3.5%", date(2023, 1, 1), attr="forex_markup")],
    }
    rows = {r["attribute"]: r for r in then_vs_now(by, date(2024, 1, 1), date(2026, 1, 1))}
    assert (
        rows["annual_fee"]["changed"]
        and rows["annual_fee"]["then"]["values"][0]["value"] == "Rs 500"
    )
    assert not rows["forex_markup"]["changed"]
    ch = changes_between(by, date(2024, 1, 1), date(2026, 1, 1))
    assert [(c.attribute, c.after.values[0].value) for c in ch] == [("annual_fee", "Rs 999")]


def test_a_value_dated_only_by_when_ritam_read_it_is_never_a_change():
    by = {"annual_fee": [_v("Rs 500", date(2023, 1, 1), amount=500),
                         _v("Rs 999", date(2026, 11, 1), by="read", amount=999)]}  # fmt: skip
    assert changes_between(by, date(2024, 1, 1), date(2026, 12, 1)) == []


def test_ombudsman_scheme_follows_the_date():
    assert ombudsman_on(date(2025, 5, 1)).key == "rbios2021"
    assert ombudsman_on(date(2026, 7, 1)).key == "rbios2026"
    old = complaint_timeline(date(2025, 3, 1))
    assert old[-1].when == date(2026, 3, 31) and "2021" in old[-1].why  # 30 days + one year
    new = complaint_timeline(date(2026, 11, 1))
    assert new[-1].when == date(2027, 3, 1) and "2026" in new[-1].why


def test_old_bills_are_flagged_as_predating_the_card_rules():
    assert card_rule_note(date(2016, 10, 20)) is not None
    assert card_rule_note(date(2023, 1, 1)) is None and card_rule_note(None) is None


def test_free_text_differences_are_maybe_not_certain():
    by = {"reward_rate": [_v("2.5%", date(2023, 1, 1), attr="reward_rate"),
                          _v("3 points per Rs 150", date(2024, 9, 1), attr="reward_rate")]}  # fmt: skip
    row = then_vs_now(by, date(2024, 1, 1), date(2025, 1, 1))[0]
    assert row["changed"] == "maybe"
    assert changes_between(by, date(2024, 1, 1), date(2025, 1, 1))[0].as_dict()["certain"] is False


def test_slabs_on_the_same_day_are_one_set_not_a_series_of_changes():
    slabs = [
        _v(f"Rs {a}", date(2026, 8, 28), amount=a, attr="late_payment_fee", cid=str(a))
        for a in (0, 500, 750, 1200, 1300)
    ]
    old = [
        _v(f"Rs {a}", date(2025, 1, 1), amount=a, attr="late_payment_fee", cid=f"o{a}")
        for a in (0, 500, 750, 1200, 1300)
    ]
    assert changes_between({"late_payment_fee": slabs}, date(2024, 1, 1), date(2027, 1, 1)) == []
    # Same slabs a year apart: still no change.
    assert (
        changes_between({"late_payment_fee": old + slabs}, date(2024, 1, 1), date(2027, 1, 1)) == []
    )
    # One slab raised: one certain change.
    raised = [
        *slabs[:-1],
        _v("Rs 1500", date(2026, 8, 28), amount=1500, attr="late_payment_fee", cid="n"),
    ]
    ch = changes_between({"late_payment_fee": old + raised}, date(2024, 1, 1), date(2027, 1, 1))
    assert len(ch) == 1 and ch[0].as_dict()["certain"] is True


def test_nil_free_and_no_fee_all_mean_zero():
    by = {
        "annual_fee": [
            _v("no joining or annual fee", date(2024, 1, 1)),
            _v("Nil", date(2026, 11, 10)),
        ]
    }
    assert changes_between(by, date(2023, 1, 1), date(2027, 1, 1)) == []
