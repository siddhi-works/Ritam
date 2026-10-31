"""Rule engine tests on a sample devaluation scenario."""

from datetime import date
from typing import Any

import pytest

from app.analysis.checklist import FORBIDDEN_WORDS, build_checklist
from app.analysis.copydetect import copy_edges, single_origin_findings
from app.analysis.facts import ClaimFact, Finding, SourceFact, SubQuestion
from app.analysis.rules import Analysis
from app.extract.normalize import normalize_value
from app.packs import load_pack

PACK = load_pack()
TODAY = date(2026, 10, 31)
AGG_TEXT = (
    "Magnus credit card review. Enjoy unlimited complimentary domestic lounge access at airports "
    "across India with your card, plus attractive rewards on every spend and a welcome benefit "
    "for new customers who apply online through our comparison platform today."
)


def src(id: str, kind: str, tier: int, **kw: Any) -> SourceFact:
    kw.setdefault("date_confidence", 0.9)
    kw.setdefault("observed_at", date(2026, 10, 30))
    return SourceFact(id=id, kind=kind, tier=tier, title=kw.pop("title", id), **kw)


def claim(id: str, source: str, attribute: str, raw: str, **kw: Any) -> ClaimFact:
    spec = PACK.get(attribute)
    assert spec is not None
    return ClaimFact(
        id=id, source_id=source, attribute=attribute, value_raw=raw,
        value_norm=normalize_value(raw, spec.value_type), quote=f"... {raw} ...", page_no=1, **kw,
    )  # fmt: skip


SOURCES = [
    src("mitc_old", "mitc_pdf", 1, effective_from=date(2025, 1, 1),
        pages=("Annual fee Rs 12,500. Domestic lounge: unlimited. Card closure on request.",)),
    src("mitc_new", "mitc_pdf", 1, effective_from=date(2026, 8, 28),
        pages=("Annual fee Rs 12,500. Domestic lounge: 8 per year. Forex markup 2%. "
               "Any change in charges with one month notice. Closure of card on request.",)),
    src("page", "official_page", 1, effective_from=date(2026, 8, 28), url="https://bank.test/magnus"),
    src("notice", "bank_notice", 1, announced_at=date(2026, 8, 10), effective_from=date(2026, 8, 28)),
    src("agg1", "aggregator", 3, title="CompareCards", pages=(AGG_TEXT,)),
    src("agg2", "aggregator", 3, title="CardCopycat", date_confidence=None, pages=(AGG_TEXT,)),
    src("chat", "user_chat", 4, said_at=date(2026, 9, 10)),
    src("moved", "official_page", 1, redirected_to="https://bank.test/other-card"),
]  # fmt: skip
CLAIMS = [
    claim("c1", "mitc_old", "domestic_lounge_visits", "unlimited"),
    claim("c2", "mitc_new", "domestic_lounge_visits", "8 per year"),
    claim("c3", "mitc_new", "annual_fee", "Rs 12,500"),
    claim("c4", "page", "annual_fee", "Rs 10,000"),  # bank page disagrees with its own MITC
    claim("c5", "notice", "forex_markup", "2%", valid_from=date(2026, 8, 28)),
    claim("c6", "agg1", "domestic_lounge_visits", "unlimited"),  # still shows the old value
    claim("c7", "agg2", "domestic_lounge_visits", "unlimited"),
    claim("c8", "chat", "forex_markup", "1.5%"),  # what customer care said
    claim("c9", "mitc_new", "forex_markup", "2%"),
    claim("c10", "moved", "annual_fee", "Rs 500"),  # different product: must be ignored
]
QUESTIONS = [
    SubQuestion("Is there a cash withdrawal fee?", ("cash_advance_fee",)),
    SubQuestion("How do I close the card?", ("card_closure",)),
]


@pytest.fixture(scope="module")
def findings() -> list[Finding]:
    return Analysis(PACK, SOURCES, CLAIMS, sub_questions=QUESTIONS, today=TODAY).run()


def by_rule(findings: list[Finding], rule: str) -> list[Finding]:
    return [f for f in findings if f.rule_id == rule]


def test_bank_contradicting_itself_is_flagged(findings: list[Finding]) -> None:
    (f,) = [f for f in findings if f.key == "conflict:annual_fee"]
    assert f.subtype == "self" and f.label == "sourced"
    assert set(f.claim_ids) == {"c3", "c4"}  # the redirected page's Rs 500 is not in it
    assert "moved" not in f.source_ids


def test_stale_comparison_site_with_days_and_old_value_match(findings: list[Finding]) -> None:
    stale = by_rule(findings, "stale.aggregator")
    assert {f.source_ids[0] for f in stale} == {"agg1", "agg2"}
    f = stale[0]
    assert f.detail["stale_since"] == "2026-08-28" and f.detail["days_stale"] == 64
    assert f.detail["matches_older_issuer_value"] is True
    assert "stale since 28 Aug 2026, 64 days" in f.title


def test_short_notice_on_a_charge(findings: list[Finding]) -> None:
    (f,) = by_rule(findings, "notice.short")
    assert f.detail["notice_days"] == 18 and f.label == "sourced" and f.severity == 5
    assert f.detail["charge_attributes"] == ["forex_markup"]
    assert "verify" in f.title


def test_chat_checked_against_terms_valid_on_that_date(findings: list[Finding]) -> None:
    (f,) = by_rule(findings, "chat.mismatch")
    assert f.detail["said_at"] == "2026-09-10"
    assert {e["value"] for e in f.detail["terms_valid_then"]} == {"2%"}


def test_undated_and_redirect(findings: list[Finding]) -> None:
    assert [f.source_ids for f in by_rule(findings, "undated.source")] == [["agg2"]]
    (r,) = by_rule(findings, "stale.redirect")
    assert r.label == "uncertain" and r.detail["redirected_to"].endswith("other-card")


def test_missing_mitc_terms_use_the_absence_check(findings: list[Finding]) -> None:
    missing = {f.attribute: f for f in findings if f.type == "mitc_missing"}
    # Mentioned in the MITC text but never extracted → "check page", not "not found".
    assert missing["card_closure"].subtype == "mentioned_unextracted"
    assert missing["card_closure"].label == "uncertain"
    assert missing["notice_period"].subtype == "mentioned_unextracted"
    # Never mentioned anywhere → a sourced absence.
    assert missing["late_payment_fee"].subtype == "absent"
    assert "not found in 2 page(s)" in missing["late_payment_fee"].title
    assert "forex_markup" not in missing and "annual_fee" not in missing


def test_unanswered_questions(findings: list[Finding]) -> None:
    q = {f.detail["question"]: f for f in by_rule(findings, "gap.question")}
    assert q["Is there a cash withdrawal fee?"].label == "ai_suggestion"
    assert q["How do I close the card?"].label == "uncertain"  # topic mentioned in MITC


def test_copy_detection_and_single_origin() -> None:
    edges = copy_edges(SOURCES)
    assert [(e.copier, e.original) for e in edges] == [("agg2", "agg1")]
    single = single_origin_findings(
        SOURCES, [c for c in CLAIMS if c.source_id in {"agg1", "agg2"}], edges
    )
    assert len(single) == 1 and single[0].label == "uncertain"


def test_temporal_change_is_not_called_a_conflict() -> None:
    sources = [
        src("a", "mitc_pdf", 1, effective_from=date(2025, 1, 1)),
        src("b", "official_page", 1, effective_from=date(2026, 8, 28)),
    ]
    claims = [claim("x", "a", "annual_fee", "Rs 500"), claim("y", "b", "annual_fee", "Rs 1,000")]
    (f,) = Analysis(PACK, sources, claims, today=TODAY).conflicts_and_stale()[0]
    assert f.subtype == "temporal"


def test_scope_difference_is_uncertain() -> None:
    sources = [src("a", "aggregator", 3), src("b", "aggregator", 3)]
    claims = [
        claim("x", "a", "annual_fee", "Rs 500", conditions="first year"),
        claim("y", "b", "annual_fee", "Rs 1,000"),
    ]
    (f,) = Analysis(PACK, sources, claims, today=TODAY).conflicts_and_stale()[0]
    assert f.subtype == "scope" and f.label == "uncertain"


def test_equivalent_values_do_not_conflict() -> None:
    sources = [src("a", "mitc_pdf", 1), src("b", "aggregator", 3)]
    claims = [
        claim("x", "a", "finance_charge", "3.75% per month"),
        claim("y", "b", "finance_charge", "45% p.a."),
        claim("p", "a", "domestic_lounge_visits", "2 per quarter"),
        claim("q", "b", "domestic_lounge_visits", "8 per year"),
    ]
    conflicts, stale = Analysis(PACK, sources, claims, today=TODAY).conflicts_and_stale()
    assert conflicts == [] and stale == []


def test_wording_never_states_a_verdict(findings: list[Finding]) -> None:
    checklist = build_checklist(findings, {s.id: s for s in SOURCES})
    texts = [f.title for f in findings] + [c.text for c in checklist]
    for text in texts:
        assert not any(w in text.lower() for w in FORBIDDEN_WORDS), text


def test_checklist_puts_actionable_high_severity_first(findings: list[Finding]) -> None:
    checklist = build_checklist(findings, {s.id: s for s in SOURCES})
    assert checklist[0].action == "grievance" and "notice" in checklist[0].text.lower()
    assert [c.rank for c in checklist] == list(range(1, len(checklist) + 1))
    assert len({c.text for c in checklist}) == len(checklist)  # no duplicate items
    assert all(c.why for c in checklist)


def test_checklist_text_never_has_placeholder_gaps(findings: list[Finding]) -> None:
    for c in build_checklist(findings, {s.id: s for s in SOURCES}, limit=50):
        assert "the this" not in c.text and "this term" not in c.text, c.text


def test_notice_with_only_a_file_timestamp_is_uncertain_and_passing_notice_is_reported() -> None:
    # Modelled on Axis's Magnus notice: no stated date, PDF created 27 Jul, effective 28 Aug.
    sources = [src("n", "bank_notice", 1, published_at=date(2026, 7, 27), date_confidence=0.45)]
    claims = [
        claim("f1", "n", "forex_markup", "2%", valid_from=date(2026, 8, 28)),
        claim("f2", "n", "late_payment_fee", "INR 1,300", valid_from=date(2026, 8, 28)),
    ]
    (ok,) = Analysis(PACK, sources, claims, today=TODAY).notice()
    assert ok.rule_id == "notice.adequate" and ok.detail["notice_days"] == 32
    assert (
        ok.label == "uncertain"
        and ok.detail["announcement_date_source"] == "inferred_from_file_timestamp"
    )
    assert "file date 27 Jul 2026" in ok.title

    short = [src("n", "bank_notice", 1, published_at=date(2026, 8, 20), date_confidence=0.45)]
    (f,) = Analysis(PACK, short, claims, today=TODAY).notice()
    assert (
        f.rule_id == "notice.short" and f.label == "uncertain"
    )  # strong signal, but inferred date


def test_two_versions_of_a_bank_document_are_not_copying() -> None:
    text = (AGG_TEXT + " ") * 2
    sources = [
        src("old", "mitc_pdf", 1, effective_from=date(2025, 1, 1), pages=(text,)),
        src("new", "mitc_pdf", 1, effective_from=date(2026, 8, 28), pages=(text,)),
    ]
    assert copy_edges(sources) == []


async def test_retry_db_recovers_from_a_dropped_connection() -> None:
    from app.audit.pipeline import _retry_db

    class FakeSession:
        rollbacks = 0
        refreshed: list[object] = []

        async def rollback(self) -> None:
            self.rollbacks += 1

        async def refresh(self, obj: object) -> None:
            self.refreshed.append(obj)

    calls = {"n": 0}

    async def op() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionResetError("WinError 10054")
        return "saved"

    s = FakeSession()
    marker = object()
    assert await _retry_db(s, op, refresh=[marker]) == "saved"  # type: ignore[arg-type]
    assert calls["n"] == 2 and s.rollbacks == 1 and s.refreshed == [marker]


def test_value_the_bank_never_published_is_a_conflict_not_staleness() -> None:
    sources = [
        src("notice", "bank_notice", 1, effective_from=date(2026, 8, 28)),
        src("press", "news", 3, title="BusinessToday"),
    ]
    claims = [
        claim("n", "notice", "dcc_markup", "2%", valid_from=date(2026, 8, 28)),
        claim("p", "press", "dcc_markup", "3.5%"),
    ]
    conflicts, stale = Analysis(PACK, sources, claims, today=TODAY).conflicts_and_stale()
    assert stale == [] and len(conflicts) == 1


def test_checklist_uses_feature_labels() -> None:
    f = Finding(
        type="mitc_missing",
        rule_id="mitc_missing.absent",
        label="sourced",
        severity=4,
        confidence=0.7,
        title="t",
        attribute="card_closure",
        key="k",
    )
    (item,) = build_checklist([f], {}, labels={a.key: a.label for a in PACK.attributes})
    assert "card closure process" in item.text


def test_general_pack_flags_deadline_conflicts_with_its_own_wording() -> None:
    general = load_pack("general")

    def gclaim(id: str, source: str, attribute: str, raw: str) -> ClaimFact:
        spec = general.get(attribute)
        assert spec is not None
        return ClaimFact(
            id=id, source_id=source, attribute=attribute, value_raw=raw,
            value_norm=normalize_value(raw, spec.value_type), quote=f"... {raw} ...", page_no=1,
        )  # fmt: skip

    sources = [
        src("portal", "official_page", 1, effective_from=date(2026, 10, 1), url="https://scholarships.gov.in/"),
        src("guide", "official_page", 1, effective_from=date(2026, 7, 1), url="https://scholarships.gov.in/g.pdf"),
        src("notice", "bank_notice", 1, announced_at=date(2026, 10, 20), effective_from=date(2026, 10, 25)),
        src("blog", "aggregator", 3, title="ScholarBlog"),
    ]  # fmt: skip
    claims = [
        gclaim("g1", "portal", "application_deadline", "31 October 2026"),
        gclaim("g2", "guide", "application_deadline", "15.10.2026"),
        gclaim("g3", "blog", "application_deadline", "15th Oct 2026"),
        gclaim("g4", "notice", "benefit_amount", "Rs 12,000 per annum"),
    ]
    findings = Analysis(general, sources, claims, today=TODAY).run()
    assert not [f for f in findings if f.type in {"notice", "mitc_missing"}]  # card-only rules
    conflicts = [
        f for f in findings if f.type == "conflict" and f.attribute == "application_deadline"
    ]
    assert conflicts
    titles = " ".join(f.title for f in findings)
    assert "the bank" not in titles
    items = build_checklist(findings, {s.id: s for s in sources}, pack=general)
    text = " ".join(i.text for i in items)
    assert "the bank" not in text and "MITC" not in text


@pytest.mark.parametrize(
    ("cond", "product", "expected"),
    [
        ("previously 1.5%", None, ""),  # history, not scope
        ("extended from 15 October 2026", None, ""),
        (
            "National Means-cum-Merit (NMMSS)",
            "National Means-cum-Merit Scholarship (NMMSS) 2026-27",
            "",
        ),
        ("Magnus Burgundy variant", "Axis Bank Magnus credit card", "magnus burgundy variant"),
        ("first year only", "Axis Bank Magnus credit card", "first year only"),
    ],
)
def test_conditions_that_do_not_change_scope(cond: str, product: str | None, expected: str) -> None:
    from app.analysis.rules import _norm_cond

    assert _norm_cond(cond, product) == expected
