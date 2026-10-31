from app.analysis.compare import comparable, same_value
from app.extract.normalize import normalize_value
from app.extract.prompt import PROMPT_VERSION, scope_key, system_prompt
from app.packs import load_pack


def test_packs_load_with_disjoint_keys() -> None:
    card, general = load_pack("credit_card"), load_pack("general")
    assert not set(card.keys) & set(general.keys)  # attribute table is keyed by key alone
    assert card.prompt_version == PROMPT_VERSION
    assert general.prompt_version != card.prompt_version
    assert not any(a.mitc_required for a in general.attributes)
    assert general.notice_rules is False


def test_system_prompt_is_pack_specific() -> None:
    card = system_prompt(load_pack("credit_card"))
    general = system_prompt(load_pack("general"))
    assert "an Indian credit card" in card and "dcc_markup" in card
    assert "scholarship" in general and "dcc_markup" not in general
    assert "application_deadline" in general and "the official body" in general


def test_scope_key_separates_packs_for_the_same_product() -> None:
    general = load_pack("general")
    assert scope_key("NSP", general.prompt_version) != scope_key("NSP")
    assert scope_key(None, general.prompt_version) == general.prompt_version


def test_deadlines_compare_as_dates() -> None:
    a = normalize_value("31 October 2026", "date")
    b = normalize_value("31.10.2026", "date")
    c = normalize_value("15th Oct 2026", "date")
    assert comparable(a, b) and same_value(a, b)
    assert comparable(a, c) and not same_value(a, c)
    assert normalize_value("will be announced soon", "date")["parsed"] is False


def test_date_values_are_checked_as_dates_not_digits() -> None:
    from app.extract.service import _value_supported

    quote = "has been extended to September 30, 2026."
    assert _value_supported("30.09.2026", quote, "date")
    assert _value_supported("September 30, 2026", "| Last date | 30.09.2026 |", "date")
    assert not _value_supported("31.10.2026", quote, "date")  # a different date is still dropped
    assert not _value_supported("30.09.2026", quote, "money")  # other types keep the digit check
