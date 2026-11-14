"""How rewards are paid: the "called cashback, paid as vouchers" rule, what points are worth,
and reading older reports after the extraction version changed."""

from types import SimpleNamespace
from typing import Any, cast

from app.analysis.rewards import points_rate, reward_forms
from app.analysis.rules import Analysis
from app.api.audits import claim_scope
from app.extract.prompt import scope_key
from tests.test_rules import PACK, TODAY, claim, src

MITC = src("mitc", "mitc_pdf", 1)
BLOG = src("blog", "aggregator", 3)


def run(*claims: Any, product: str = "Shop Cashback credit card") -> list[Any]:
    return Analysis(PACK, [MITC, BLOG], claims, today=TODAY, product=product).rewards()


def test_forms_are_read_from_the_terms_wording():
    assert reward_forms("Cashback will be credited to your card account") == {"money"}
    assert reward_forms("Cashback is given as Amazon Pay balance") == {"wallet"}
    assert reward_forms("redeemable as e-gift vouchers") == {"vouchers"}
    assert reward_forms("Earn 2 reward points") == {"points"}


def test_points_rate_and_real_value():
    r = points_rate("4 Reward Points per Rs 150 spent")
    assert r is not None and (r.points, r.per_rupees) == (4, 150)
    assert round(r.percent(0.25), 2) == 0.67
    assert points_rate("5% cashback on online spends") is None


def test_cashback_paid_as_vouchers_is_flagged_from_the_banks_own_terms():
    out = run(
        claim("f", "mitc", "reward_form", "Cashback is issued as gift vouchers"),
        claim("r", "mitc", "reward_rate", "5% cashback on online spends"),
    )
    assert [f.rule_id for f in out] == ["gap.cashback_form"]
    assert out[0].title == "Called cashback, but paid as vouchers or gift cards"
    assert out[0].label == "sourced" and out[0].claim_ids == ["f"]


def test_money_off_the_bill_or_a_blog_saying_vouchers_is_not_flagged():
    assert (
        run(claim("f", "mitc", "reward_form", "Cashback will be credited to your card account"))
        == []
    )
    # Only the bank's own documents decide how rewards are paid.
    assert run(claim("f", "blog", "reward_form", "Cashback comes as gift vouchers")) == []


def test_points_card_gets_its_real_value_in_percent():
    out = run(
        claim("r", "mitc", "reward_rate", "4 reward points per Rs 150"),
        claim("v", "mitc", "point_value", "1 reward point = Rs 0.25"),
        product="Shop Platinum credit card",
    )
    assert [f.rule_id for f in out] == ["gap.points_value"]
    assert "0.67%" in out[0].detail["reasons"][0]


def test_an_implausible_point_value_is_ignored():
    out = run(
        claim("r", "mitc", "reward_rate", "4 reward points per Rs 150"),
        claim("v", "mitc", "point_value", "Rs 250"),
        product="Shop Platinum credit card",
    )
    assert out == []


def test_old_reports_keep_reading_their_own_facts():
    old = cast(Any, SimpleNamespace(product_name="X card", stats={"trace": []}))
    new = cast(Any, SimpleNamespace(product_name="X card", stats={"claim_scope": "kept"}))
    assert claim_scope(old, PACK) == scope_key("X card", PACK.previous_prompt_versions[-1])
    assert claim_scope(new, PACK) == "kept"
    assert PACK.prompt_version not in PACK.previous_prompt_versions


def test_point_value_reads_the_rupee_side():
    from app.analysis.rewards import rupees_per_point

    assert rupees_per_point("1 reward point = Rs 0.25") == 0.25
    assert rupees_per_point("each point is worth 20 paise") == 0.2
    assert rupees_per_point("Rs 0.30 per point") == 0.3
    assert rupees_per_point("Rs 250") is None
