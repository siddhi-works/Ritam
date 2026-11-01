from app.analysis.compare import comparable, same_value
from app.extract.normalize import normalize_value


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
