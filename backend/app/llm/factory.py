from pydantic import SecretStr

from app.config import Settings
from app.llm.base import ProviderAdapter, Task
from app.llm.gemini import GeminiAdapter
from app.llm.openai_compat import OPENAI_COMPATIBLE_BASE_URLS, OpenAICompatAdapter
from app.llm.router import LLMRouter, Route


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value else None


def make_router(settings: Settings) -> LLMRouter:
    timeout = settings.llm_timeout_s
    adapters: dict[str, ProviderAdapter] = {
        "gemini": GeminiAdapter(
            _secret(settings.gemini_api_key), base_url=settings.gemini_base_url, timeout_s=timeout
        ),
        "groq": OpenAICompatAdapter(
            "groq",
            _secret(settings.groq_api_key),
            base_url=OPENAI_COMPATIBLE_BASE_URLS["groq"],
            timeout_s=timeout,
        ),
        "mistral": OpenAICompatAdapter(
            "mistral",
            _secret(settings.mistral_api_key),
            base_url=OPENAI_COMPATIBLE_BASE_URLS["mistral"],
            timeout_s=timeout,
        ),
        "openrouter": OpenAICompatAdapter(
            "openrouter",
            _secret(settings.openrouter_api_key),
            base_url=OPENAI_COMPATIBLE_BASE_URLS["openrouter"],
            timeout_s=timeout,
            extra_headers={"X-Title": "Ritam"},
        ),
    }
    chains: dict[Task, list[Route]] = {
        "extract": [Route.parse(s) for s in settings.llm_extract_chain],
        "reason": [Route.parse(s) for s in settings.llm_reason_chain],
    }
    unknown = {r.provider for rs in chains.values() for r in rs} - adapters.keys()
    if unknown:
        raise ValueError(f"unknown LLM providers in chain config: {sorted(unknown)}")
    return LLMRouter(
        adapters,
        chains,
        rpm=settings.llm_rpm,
        max_attempts_per_route=settings.llm_max_attempts_per_route,
    )
