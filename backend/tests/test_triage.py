from types import SimpleNamespace

from app.triage import route
from evals.triage import CASES, HELD_OUT, run, score


async def test_router_rules_pass_the_labelled_set_and_card_names():
    out = await run()
    assert out["correct"] == 1.0, out["wrong"]
    assert out["card_wrong"] == []


async def test_fraud_is_caught_by_rules_alone_on_every_message():
    # Safety must not depend on an AI provider being up.
    fraud = [c for c in CASES + HELD_OUT if c[1] == "fraud"]
    acc, wrong = await score(fraud)
    assert acc == 1.0, wrong


async def test_unseen_messages_with_rules_only_never_go_to_a_wrong_problem():
    # Rules may say "don't know" (the AI then decides) but must not pick a wrong problem.
    _, wrong = await score(HELD_OUT)
    assert all(got is None for _, _, got in wrong), wrong


class _AI:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    async def generate_structured(self, *, prompt, **_):
        self.prompts.append(prompt)
        return SimpleNamespace(data=SimpleNamespace(problem=self.answer))


async def test_ai_fallback_is_masked_limited_to_the_list_and_only_when_rules_find_nothing():
    ai = _AI("limit_cut")
    r = await route("my credit limit got slashed to half overnight, call me on 9876543210", ai)
    assert r.problem.key == "limit_cut" and r.matched_by == "ai"  # type: ignore[union-attr]
    assert "9876543210" not in ai.prompts[0]
    junk = await route("my credit limit got slashed to half overnight", _AI("delete_all_users"))
    assert junk.problem is None and junk.matched_by == "none"
    ruled = _AI("card_info")
    await route("Swiggy charged me twice for the same order", ruled)
    assert ruled.prompts == []  # rules decided; no AI call


async def test_prefill_card_dates_and_foreign_cards():
    r = (
        await route("I asked for closure of my Axis ACE card on 06/11/2026, still active")
    ).as_dict()
    assert r["problem"] == "closure" and r["tool"] == "closure_claim"
    assert r["prefill"]["card_id"] == "axis-ace" and r["prefill"]["dates"] == ["2026-11-06"]
    assert (await route("Chase Sapphire annual fee charged")).not_indian
    none = (await route("hmm")).as_dict()
    assert none["problem"] is None and "block the card" in none["steps"][0]
