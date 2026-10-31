from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel

from app.llm import LLMError, LLMRouter, LLMUnavailable, Route
from app.llm.base import (
    AuthFailed,
    BadRequest,
    Completion,
    InvalidOutput,
    ModelMissing,
    Overloaded,
    RateLimited,
)

Step = Completion | Exception


class Fee(BaseModel):
    value: str
    quote: str


GOOD = Completion('{"value": "1000", "quote": "Rs 1000"}', 5, 3)


class FakeAdapter:
    def __init__(self, name: str, script: dict[str, list[Step]], configured: bool = True):
        self.name = name
        self._script = script
        self._configured = configured
        self.calls: list[str] = []

    def is_configured(self) -> bool:
        return self._configured

    async def complete_json(self, *, model: str, **_: Any) -> Completion:
        self.calls.append(model)
        steps = self._script[model]
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        if isinstance(step, Exception):
            raise step
        return step

    async def aclose(self) -> None:
        return None


async def _no_sleep(_: float) -> None:
    return None


def make(
    adapters: list[FakeAdapter], chain: list[str], clock: Callable[[], float] | None = None
) -> LLMRouter:
    kwargs: dict[str, Any] = {"clock": clock} if clock else {}
    return LLMRouter(
        {a.name: a for a in adapters},
        {"extract": [Route.parse(s) for s in chain]},
        rpm={},
        default_rpm=10_000,
        sleep=_no_sleep,
        **kwargs,
    )


async def run(router: LLMRouter) -> Any:
    return await router.generate_structured(task="extract", system="s", prompt="p", schema=Fee)


def test_route_parse_keeps_colons_in_model_id() -> None:
    r = Route.parse("openrouter:meta-llama/llama-3.3-70b-instruct:free")
    assert (r.provider, r.model) == ("openrouter", "meta-llama/llama-3.3-70b-instruct:free")
    with pytest.raises(ValueError):
        Route.parse("no-colon")


async def test_success_returns_provider_model_and_usage() -> None:
    g = FakeAdapter("gemini", {"m1": [GOOD]})
    res = await run(make([g], ["gemini:m1"]))
    assert (res.provider, res.model, res.input_tokens, res.output_tokens) == ("gemini", "m1", 5, 3)
    assert res.data == Fee(value="1000", quote="Rs 1000")


async def test_code_fenced_json_is_accepted() -> None:
    fenced = Completion('```json\n{"value": "v", "quote": "q"}\n```')
    res = await run(make([FakeAdapter("groq", {"m": [fenced]})], ["groq:m"]))
    assert res.data.quote == "q"


async def test_unconfigured_provider_routes_are_skipped() -> None:
    off = FakeAdapter("groq", {"m": [GOOD]}, configured=False)
    on = FakeAdapter("gemini", {"m": [GOOD]})
    res = await run(make([off, on], ["groq:m", "gemini:m"]))
    assert res.provider == "gemini" and off.calls == []


async def test_no_configured_route_raises_llm_error() -> None:
    off = FakeAdapter("groq", {"m": [GOOD]}, configured=False)
    with pytest.raises(LLMError) as exc:
        await run(make([off], ["groq:m"]))
    assert not isinstance(exc.value, LLMUnavailable)


async def test_overloaded_retries_then_falls_back_across_providers() -> None:
    g = FakeAdapter("gemini", {"m1": [Overloaded("503")]})
    q = FakeAdapter("groq", {"m2": [GOOD]})
    res = await run(make([g, q], ["gemini:m1", "groq:m2"]))
    assert g.calls == ["m1", "m1", "m1"] and res.provider == "groq"


async def test_per_minute_429_retries_same_route() -> None:
    g = FakeAdapter("gemini", {"m": [RateLimited("429", retry_after=3), GOOD]})
    res = await run(make([g], ["gemini:m"]))
    assert g.calls == ["m", "m"] and res.model == "m"


async def test_daily_429_cools_route_down_until_an_hour_passes() -> None:
    now = [0.0]
    g = FakeAdapter("gemini", {"m1": [RateLimited("429", daily=True), GOOD], "m2": [GOOD]})
    router = make([g], ["gemini:m1", "gemini:m2"], clock=lambda: now[0])
    assert (await run(router)).model == "m2"
    assert (await run(router)).model == "m2"  # m1 still cooling down: not called again
    assert g.calls == ["m1", "m2", "m2"]
    now[0] = 3601.0
    assert (await run(router)).model == "m1"


async def test_auth_failure_disables_every_route_of_that_provider() -> None:
    q = FakeAdapter("groq", {"a": [AuthFailed("401")], "b": [GOOD]})
    g = FakeAdapter("gemini", {"m": [GOOD]})
    router = make([q, g], ["groq:a", "groq:b", "gemini:m"])
    res = await run(router)
    assert res.provider == "gemini" and q.calls == ["a"]
    assert router.configured_providers() == ["gemini"]


async def test_model_missing_and_bad_request_skip_route_without_retry() -> None:
    g = FakeAdapter("gemini", {"gone": [ModelMissing("404")], "bad": [BadRequest("400")]})
    q = FakeAdapter("groq", {"m": [GOOD]})
    res = await run(make([g, q], ["gemini:gone", "gemini:bad", "groq:m"]))
    assert g.calls == ["gone", "bad"] and res.provider == "groq"


async def test_schema_violation_and_invalid_output_retry_same_route() -> None:
    g = FakeAdapter("gemini", {"m": [Completion('{"value": "x"}'), InvalidOutput("SAFETY"), GOOD]})
    res = await run(make([g], ["gemini:m"]))
    assert g.calls == ["m", "m", "m"] and res.data.value == "1000"


async def test_all_routes_failing_raises_unavailable_with_attempt_log() -> None:
    g = FakeAdapter("gemini", {"m": [Overloaded("503")]})
    with pytest.raises(LLMUnavailable) as exc:
        await run(make([g], ["gemini:m"]))
    assert "overloaded" in str(exc.value)


async def test_unexpected_adapter_exception_skips_route_instead_of_crashing() -> None:
    broken = FakeAdapter("mistral", {"m": [AttributeError("'list' object has no attribute")]})
    ok = FakeAdapter("gemini", {"m": [GOOD]})
    res = await run(make([broken, ok], ["mistral:m", "gemini:m"]))
    assert res.provider == "gemini" and broken.calls == ["m"]


class FakeBudget:
    def __init__(self, exhausted: set[str]):
        self.exhausted = exhausted
        self.recorded: list[str] = []

    async def allow(self, provider: str) -> bool:
        return provider not in self.exhausted

    async def record(self, provider: str) -> None:
        self.recorded.append(provider)


async def test_budget_skips_exhausted_provider_and_counts_attempts() -> None:
    g = FakeAdapter("gemini", {"m": [GOOD]})
    q = FakeAdapter("groq", {"m": [Overloaded("503"), GOOD]})
    router = make([g, q], ["gemini:m", "groq:m"])
    router.budget = FakeBudget(exhausted={"gemini"})
    res = await run(router)
    assert res.provider == "groq" and g.calls == []
    assert router.budget.recorded == ["groq", "groq"]  # every attempt counts, including failures
    assert res.attempts[0]["error"] == "daily_budget_reached"


def test_quota_day_is_pacific_time() -> None:
    from datetime import UTC, date, datetime

    from app.llm.budget import quota_day

    # 13:00 IST on 1 Nov 2026 = 07:30 UTC = 00:30 PDT on 1 Nov; 12:00 IST = 23:30 PDT on 31 Oct.
    assert quota_day(datetime(2026, 11, 1, 7, 30, tzinfo=UTC)) == date(2026, 11, 1)
    assert quota_day(datetime(2026, 11, 1, 6, 30, tzinfo=UTC)) == date(2026, 10, 31)
