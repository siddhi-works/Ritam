"""One adapter for every OpenAI-compatible `/chat/completions` API (Groq, Mistral, OpenRouter)."""

import re
from typing import Any

import httpx

from app.llm.base import (
    AuthFailed,
    BadRequest,
    Completion,
    InvalidOutput,
    ModelMissing,
    Overloaded,
    RateLimited,
)
from app.llm.schema import schema_instruction

# Groq: "...on tokens per day (TPD)..."; OpenRouter: "free-models-per-day".
_DAILY = re.compile(r"per[ -]day|\bTPD\b|\bRPD\b", re.I)
_SCHEMA_UNSUPPORTED = re.compile(r"response_format|json_schema|structured", re.I)

OPENAI_COMPATIBLE_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class OpenAICompatAdapter:
    """Tries native `json_schema` output first. If a model rejects it, that model is remembered
    and downgraded to `json_object` mode with the schema in the system prompt."""

    def __init__(
        self,
        name: str,
        api_key: str | None,
        *,
        base_url: str,
        timeout_s: float = 60.0,
        extra_headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._extra_headers = extra_headers or {}
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._owns_client = client is None
        self._no_native_schema: set[str] = set()

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def complete_json(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        json_schema: dict[str, Any],
        schema_name: str,
        temperature: float,
    ) -> Completion:
        native = model not in self._no_native_schema
        try:
            return await self._call(
                model, system, prompt, json_schema, schema_name, temperature, native
            )
        except BadRequest as exc:
            if native and _SCHEMA_UNSUPPORTED.search(str(exc)):
                self._no_native_schema.add(model)
                return await self._call(
                    model, system, prompt, json_schema, schema_name, temperature, False
                )
            raise

    async def _call(
        self,
        model: str,
        system: str,
        prompt: str,
        json_schema: dict[str, Any],
        schema_name: str,
        temperature: float,
        native: bool,
    ) -> Completion:
        if native:
            response_format: dict[str, Any] = {
                "type": "json_schema",
                # strict=False: strict mode demands every property be required, which would
                # forbid optional fields in our Pydantic models.
                "json_schema": {"name": schema_name, "schema": json_schema, "strict": False},
            }
            system_text = system
        else:
            response_format = {"type": "json_object"}
            system_text = f"{system}\n\n{schema_instruction(json_schema)}"

        body = {
            "model": model,
            "temperature": temperature,
            # Mistral rejects temperature=0 unless top_p is exactly 1 ("greedy sampling").
            "top_p": 1,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": prompt},
            ],
            "response_format": response_format,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", **self._extra_headers}
        try:
            resp = await self._client.post(
                f"{self._base_url}/chat/completions", json=body, headers=headers
            )
        except httpx.TransportError as exc:
            raise Overloaded(type(exc).__name__) from exc

        if resp.status_code == 200:
            return self._parse(resp.json())
        msg = f"{resp.status_code}: {_error_message(resp)[:300]}"
        if resp.status_code == 429:
            if _plan_excludes_model(resp):
                raise ModelMissing(f"{msg} (model not included in this plan: limit is 0)")
            raise RateLimited(msg, daily=bool(_DAILY.search(msg)), retry_after=_retry_after(resp))
        if resp.status_code >= 500:
            raise Overloaded(msg)
        if resp.status_code == 404:
            raise ModelMissing(msg)
        if resp.status_code == 401:
            raise AuthFailed(msg)
        # 403 is often model-specific (OpenRouter: "only available on agentic harnesses",
        # moderation), so skip just this route rather than the whole provider.
        raise BadRequest(msg)

    @staticmethod
    def _parse(payload: dict[str, Any]) -> Completion:
        choices = payload.get("choices") or []
        if not choices:
            raise InvalidOutput("no choices")
        choice = choices[0]
        if choice.get("finish_reason") in ("length", "content_filter"):
            raise InvalidOutput(f"finish reason {choice['finish_reason']}")
        text = _content_text((choice.get("message") or {}).get("content"))
        if not text.strip():
            raise InvalidOutput("empty content")
        usage = payload.get("usage") or {}
        return Completion(
            text=text,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )


def _error_message(resp: httpx.Response) -> str:
    """Groq/OpenRouter: {"error": {"message": ...}}. Mistral: {"message": ..., "type": ...}."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text
    if not isinstance(body, dict):
        return resp.text
    err = body.get("error")
    if isinstance(err, dict) and err.get("message"):
        return str(err["message"])
    if isinstance(err, str) and err:
        return err
    if body.get("message"):
        return str(body["message"])
    return resp.text


def _content_text(content: Any) -> str:
    """`content` is a string for most models, but reasoning models (e.g. mistral-large-4) return
    a list of typed parts: keep only the answer text, never the thinking."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(p.get("text", ""))
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def _plan_excludes_model(resp: httpx.Response) -> bool:
    """Mistral answers 429 with `x-ratelimit-limit-req-minute: 0` for models the free plan
    doesn't include. Retrying is pointless; the route should be skipped."""
    return any(
        k.lower().startswith("x-ratelimit-limit") and v.strip() == "0"
        for k, v in resp.headers.items()
    )


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    try:
        return float(value) if value else None
    except ValueError:
        return None
