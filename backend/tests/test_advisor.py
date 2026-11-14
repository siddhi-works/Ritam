from decimal import Decimal

from app.advisor import Answers, build, rupees


def _a(**kw):
    base = {"spend": {"online": 15000, "dining": 5000, "groceries": 4000, "fuel": 1000}}
    return Answers.model_validate({**base, **kw})


def test_indian_number_format():
    assert (
        rupees(240000) == "₹2,40,000"
        and rupees(1800) == "₹1,800"
        and rupees(12345678) == "₹1,23,45,678"
    )


def test_biggest_category_and_its_worth_in_rupees():
    c = build(_a())
    assert c.yearly_spend == 300000
    first = c.must_have[0]
    assert "online shopping" in first.text and "60%" in first.text
    assert "₹1,800 a year" in first.maths  # 1% of 15,000 x 12


def test_fee_breakeven_and_waiver_use_the_persons_spend():
    c = build(_a(max_fee=500))
    fee = next(p for p in c.must_have if "annual fee" in p.text)
    assert "0.2%" in fee.maths and "₹3,000 for each 1%" in fee.maths  # 500 / 3,00,000
    assert any("₹3,00,000" in p.text for p in c.nice_to_have)
    free = build(_a(max_fee=0))
    assert any("No annual fee" in p.text for p in free.must_have)


def test_travel_lounge_revolving_and_apps():
    c = build(
        _a(abroad_per_year=50000, lounge_visits_per_year=4, pays_in_full=False, apps=["Swiggy"])
    )
    assert c.must_have[0].text.startswith("Pay the full bill")
    forex = next(p for p in c.must_have if "foreign currency" in p.text)
    assert "₹500" in forex.maths  # 1% of 50,000
    assert any("4 visits" in p.text for p in c.nice_to_have)
    assert any("Swiggy" in p.text for p in c.nice_to_have)
    assert any("markup" in q for q in c.ask_the_bank)


def test_big_spend_on_often_excluded_category_is_a_skip_reason():
    c = build(Answers.model_validate({"spend": {"bills": 20000, "online": 2000}}))
    assert any("bills and utilities" in p.text for p in c.skip_if)


def test_benchmarks_attach_only_when_given():
    plain = build(_a(abroad_per_year=1000))
    assert all(p.benchmark is None for p in plain.must_have)
    b = build(
        _a(abroad_per_year=1000),
        {"forex_markup": "Most cards charge 2% to 3.5% (12 cards, Nov 2026)."},
    )
    assert next(p for p in b.must_have if "foreign" in p.text).benchmark


def test_no_spend_still_gives_questions():
    c = build(Answers.model_validate({"spend": {}}))
    assert c.yearly_spend == 0 and c.ask_the_bank and Decimal(0) == 0


def test_a_brand_is_weighed_against_its_own_category():
    c = build(_a(apps=["Swiggy", "Amazon"]))
    swiggy = next(p for p in c.nice_to_have if "Swiggy" in p.text)
    amazon = next(p for p in c.nice_to_have if "Amazon" in p.text)
    assert "food delivery and dining" in swiggy.maths and "20%" in swiggy.maths  # 5,000 of 25,000
    assert "online shopping" in amazon.maths and "60%" in amazon.maths
