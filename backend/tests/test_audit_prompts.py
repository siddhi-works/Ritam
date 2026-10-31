from app.analysis.facts import Finding
from app.audit import prompts
from app.packs import load_pack

PACK = load_pack()
FINDINGS = [
    Finding(
        type="notice",
        rule_id="notice.short",
        label="sourced",
        severity=5,
        confidence=0.75,
        title="May not meet the notice requirement: announced 10 Aug 2026, effective 28 Aug 2026 — verify",
        key="notice:n:2026-08-28",
    ),
    Finding(
        type="conflict",
        rule_id="conflict.self",
        label="sourced",
        severity=5,
        confidence=0.85,
        title="Possible conflict: the bank's own documents disagree on Annual / renewal fee",
        key="conflict:annual_fee",
    ),
]


def test_valid_summary_accepted() -> None:
    text = (
        "A change took effect on 28 Aug 2026 after a notice dated 10 Aug 2026, which may be short "
        "[notice:n:2026-08-28]. The bank's own documents possibly disagree on the annual fee [conflict:annual_fee]."
    )
    assert prompts.validate_summary(text, FINDINGS) == []


def test_summary_rejects_invented_numbers_keys_and_verdicts() -> None:
    assert any(
        "numeral" in p
        for p in prompts.validate_summary("Fee rose to Rs 2,000 [conflict:annual_fee].", FINDINGS)
    )
    assert any(
        "unknown keys" in p for p in prompts.validate_summary("Something [stale:x].", FINDINGS)
    )
    assert "no finding cited" in prompts.validate_summary("All good.", FINDINGS)
    assert "verdict wording" in prompts.validate_summary(
        "This is a violation [conflict:annual_fee].", FINDINGS
    )


def test_fallback_summary_cites_the_top_finding() -> None:
    text = prompts.fallback_summary(FINDINGS)
    assert prompts.validate_summary(text, FINDINGS) == [] or "[" in text
    assert "1 notice-period signals" in text and "[notice:n:2026-08-28]" in text
    assert "No potential gaps" in prompts.fallback_summary([])


def test_plan_schema_rejects_unknown_attributes() -> None:
    schema = prompts.plan_schema(PACK)
    ok = schema.model_validate(
        {
            "attributes": ["annual_fee"],
            "sub_questions": [{"text": "What is the annual fee?", "attributes": ["annual_fee"]}],
        }
    )
    attrs, subs = prompts.parse_plan(ok)
    assert attrs == ["annual_fee"] and subs[0].attributes == ("annual_fee",)
    try:
        schema.model_validate({"attributes": ["vibes"], "sub_questions": []})
    except ValueError:
        pass
    else:
        raise AssertionError("unknown attribute accepted")


def test_summary_length_limit() -> None:
    long = "The annual fee may differ [conflict:annual_fee]. " * 30
    assert "too long" in prompts.validate_summary(long, FINDINGS)
