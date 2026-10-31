from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

Task = Literal["extract", "reason"]


class LLMError(Exception):
    """A request we cannot satisfy (no provider configured, every route failed)."""


class LLMUnavailable(LLMError):
    """Every route in the fallback chain was rate-limited, overloaded, missing or invalid."""


# Adapters raise these; the router decides whether to retry, skip the route or skip the provider.
class ProviderError(Exception):
    pass


class RateLimited(ProviderError):
    def __init__(self, msg: str, *, daily: bool = False, retry_after: float | None = None):
        super().__init__(msg)
        self.daily = daily
        self.retry_after = retry_after


class Overloaded(ProviderError):
    """5xx or transport failure: worth retrying the same model."""


class ModelMissing(ProviderError):
    """404 / retired model: skip this route."""


class AuthFailed(ProviderError):
    """Bad or revoked key: skip every route of this provider for the process lifetime."""


class BadRequest(ProviderError):
    """400 we could not adapt to: skip this route."""


class InvalidOutput(ProviderError):
    """Blocked, truncated or empty output: retry the same model."""


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderAdapter(Protocol):
    """One HTTP call to one model. No retries here: the router owns retry and fallback policy."""

    name: str

    def is_configured(self) -> bool: ...

    async def complete_json(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        json_schema: dict[str, Any],
        schema_name: str,
        temperature: float,
    ) -> Completion: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    data: T
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)


class LLMProvider(Protocol):
    name: str

    async def generate_structured[T: BaseModel](
        self,
        *,
        task: Task,
        system: str,
        prompt: str,
        schema: type[T],
        temperature: float = 0.0,
    ) -> LLMResult[T]: ...

    def is_configured(self) -> bool: ...

    def configured_providers(self) -> list[str]: ...

    async def aclose(self) -> None: ...
