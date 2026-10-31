"""Value equality for the rule engine. Unparsed text and mismatched types never conflict."""

from typing import Any

_PER_YEAR = {"month": 12, "quarter": 4, "year": 1}


def comparable(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    if not a or not b or not a.get("parsed") or not b.get("parsed"):
        return False
    if a.get("type") != b.get("type") or a.get("type") == "text":
        return False
    return "value" in a and "value" in b


def _close(x: float | int | None, y: float | int | None, rel: float = 0.005) -> bool:
    if x is None or y is None:
        return x is y
    return abs(float(x) - float(y)) <= rel * max(abs(float(x)), abs(float(y)), 1.0)


def same_value(a: dict[str, Any], b: dict[str, Any]) -> bool:
    kind = a["type"]
    if kind == "date":
        return bool(a["value"] == b["value"])
    if kind == "percent":
        pa, pb = a.get("period"), b.get("period")
        if pa and pb and pa != pb and pa in _PER_YEAR and pb in _PER_YEAR:
            return _close(a["value"] * _PER_YEAR[pa], b["value"] * _PER_YEAR[pb])
        return _close(a["value"], b["value"])
    if kind == "count":
        if a.get("unlimited") or b.get("unlimited"):
            return bool(a.get("unlimited")) == bool(b.get("unlimited"))
        if "per_year" in a and "per_year" in b:
            return _close(a["per_year"], b["per_year"])
        return _close(a["value"], b["value"])
    if kind == "money":
        if not _close(a.get("value"), b.get("value")):
            return False
        return (
            a.get("percent") is None
            or b.get("percent") is None
            or _close(a["percent"], b["percent"])
        )
    return _close(a.get("value"), b.get("value"))


def display(norm: dict[str, Any] | None, raw: str) -> str:
    return raw if not norm or not norm.get("parsed") else raw.strip()
