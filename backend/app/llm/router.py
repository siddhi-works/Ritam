import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.llm.base import (
    AuthFailed,
    BadRequest,
    InvalidOutput,
    LLMError,
    LLMResult,
    LLMUnavailable,
    ModelMissing,
    Overloaded,
    ProviderAdapter,
    RateLimited,
    Task,
)
from app.llm.budget import BudgetGuard
from app.llm.ratelimit import TokenBucket
from app.llm.schema import strip_fences, to_json_schema

log = logging.getLogger(__name__)

# After a daily-quota 429, don't touch that route again for this long (re-probe hourly).
_DAILY_COOLDOWN_S = 3600.0
_MAX_RATE_LIMIT_WAIT_S = 30.0


@dataclass(frozen=True)
class Route:
    provider: str
    model: str

    @classmethod
    def parse(cls, spec: str) -> "Route":
        """`"groq:openai/gpt-oss-120b"` → Route("groq", "openai/gpt-oss-120b"). Splits on the
        first colon only, since OpenRouter model ids contain colons (`...:free`)."""
        provider, sep, model = spec.partition(":")
        if not sep or not provider or not model:
            raise ValueError(f"route must look like 'provider:model', got {spec!r}")
        return cls(provider, model)

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


class LLMRouter:
    """Walks an ordered chain of (provider, model) routes per task.

    Retry policy lives here, once, for every provider:
      - per-minute 429 / 5xx / transport error / invalid JSON → retry the same route
      - daily-quota 429 → cool the route down for an hour, move on
      - 404 or unadaptable 400 → move on
      - 401/403 → disable the whole provider for this process
    """

    name = "router"

    def __init__(
        self,
        adapters: Mapping[str, ProviderAdapter],
        chains: Mapping[Task, Sequence[Route]],
        *,
        rpm: Mapping[str, int],
        default_rpm: int = 10,
        max_attempts_per_route: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        budget: BudgetGuard | None = None,
    ) -> None:
        self.budget = budget
        self._adapters = dict(adapters)
        self._chains = {task: list(routes) for task, routes in chains.items()}
        self._rpm = dict(rpm)
        self._default_rpm = default_rpm
        self._max_attempts = max_attempts_per_route
        self._sleep = sleep
        self._clock = clock
        self._buckets: dict[Route, TokenBucket] = {}
        self._cooldown_until: dict[Route, float] = {}
        self._disabled: set[str] = set()

    def _usable(self, route: Route) -> bool:
        adapter = self._adapters.get(route.provider)
        return (
            adapter is not None
            and adapter.is_configured()
            and route.provider not in self._disabled
            and self._cooldown_until.get(route, 0.0) <= self._clock()
        )

    def routes(self, task: Task) -> list[Route]:
        return [r for r in self._chains.get(task, []) if self._usable(r)]

    def is_configured(self) -> bool:
        return any(self.routes(task) for task in self._chains)

    def configured_providers(self) -> list[str]:
        return sorted(
            name
            for name, a in self._adapters.items()
            if a.is_configured() and name not in self._disabled
        )

    async def aclose(self) -> None:
        await asyncio.gather(*(a.aclose() for a in self._adapters.values()))

    def _bucket(self, route: Route) -> TokenBucket:
        if route not in self._buckets:
            self._buckets[route] = TokenBucket(self._rpm.get(route.provider, self._default_rpm))
        return self._buckets[route]

    async def generate_structured[T: BaseModel](
        self,
        *,
        task: Task,
        system: str,
        prompt: str,
        schema: type[T],
        temperature: float = 0.0,
    ) -> LLMResult[T]:
        routes = self.routes(task)
        if not routes:
            raise LLMError(f"no configured LLM route for task {task!r}")
        json_schema = to_json_schema(schema)
        attempts: list[dict[str, Any]] = []

        for route in routes:
            if not self._usable(route):  # disabled/cooled down by an earlier route in this call
                continue
            adapter = self._adapters[route.provider]
            if self.budget is not None and not await self.budget.allow(route.provider):
                attempts.append({"route": str(route), "error": "daily_budget_reached"})
                continue
            for attempt in range(1, self._max_attempts + 1):
                await self._bucket(route).acquire()
                started = self._clock()
                record: dict[str, Any] = {"route": str(route), "attempt": attempt}
                attempts.append(record)
                if self.budget is not None:
                    await self.budget.record(route.provider)
                try:
                    completion = await adapter.complete_json(
                        model=route.model,
                        system=system,
                        prompt=prompt,
                        json_schema=json_schema,
                        schema_name=schema.__name__,
                        temperature=temperature,
                    )
                    data = schema.model_validate_json(strip_fences(completion.text))
                except RateLimited as exc:
                    record["error"] = f"rate_limited: {exc}"
                    if exc.daily:
                        self._cooldown_until[route] = self._clock() + _DAILY_COOLDOWN_S
                        break
                    wait = exc.retry_after or self._backoff(attempt)
                    await self._sleep(min(wait, _MAX_RATE_LIMIT_WAIT_S))
                    continue
                except Overloaded as exc:
                    record["error"] = f"overloaded: {exc}"
                    await self._sleep(self._backoff(attempt))
                    continue
                except (InvalidOutput, ValidationError, ValueError) as exc:
                    record["error"] = f"invalid_output: {str(exc)[:200]}"
                    continue
                except ModelMissing as exc:
                    record["error"] = f"model_missing: {exc}"
                    break
                except AuthFailed as exc:
                    record["error"] = f"auth_failed: {exc}"
                    self._disabled.add(route.provider)
                    log.error("llm provider disabled", extra={"provider": route.provider})
                    break
                except BadRequest as exc:
                    record["error"] = f"bad_request: {exc}"
                    log.error("llm bad request", extra={"route": str(route), "error": str(exc)})
                    break
                except Exception as exc:  # noqa: BLE001 - an adapter bug must not stop fallback
                    record["error"] = f"adapter_error: {type(exc).__name__}: {str(exc)[:200]}"
                    log.exception("llm adapter error", extra={"route": str(route)})
                    break

                return LLMResult(
                    data=data,
                    provider=route.provider,
                    model=route.model,
                    input_tokens=completion.input_tokens,
                    output_tokens=completion.output_tokens,
                    latency_ms=int((self._clock() - started) * 1000),
                    attempts=attempts,
                )
            log.warning("llm route exhausted", extra={"route": str(route)})

        raise LLMUnavailable(f"all routes failed: {[a.get('error') for a in attempts]}")

    @staticmethod
    def _backoff(attempt: int) -> float:
        return float(min(2 ** (attempt - 1), 20) + random.uniform(0, 0.5))  # noqa: S311
