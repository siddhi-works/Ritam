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

_BAD_FINISH = {"SAFETY", "RECITATION", "MAX_TOKENS", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
_DURATION = re.compile(r"^(\d+(?:\.\d+)?)s$")


class GeminiAdapter:
    """Gemini REST `generateContent`. The key travels only in the `x-goog-api-key` header.

    Gemma models on the same API take neither `systemInstruction` nor `responseJsonSchema`,
    so for them the system text and schema are folded into the user prompt.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._owns_client = client is None

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _native_schema(model: str) -> bool:
        return not model.startswith("gemma")

    def _body(
        self, model: str, system: str, prompt: str, json_schema: dict[str, Any], temperature: float
    ) -> dict[str, Any]:
        config: dict[str, Any] = {
            "temperature": temperature,
            "responseMimeType": "application/json",
        }
        if self._native_schema(model):
            config["responseJsonSchema"] = _gemini_compatible(json_schema)
            return {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": config,
            }
        merged = f"{system}\n\n{schema_instruction(json_schema)}\n\n{prompt}"
        return {
            "contents": [{"role": "user", "parts": [{"text": merged}]}],
            "generationConfig": config,
        }

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
        url = f"{self._base_url}/models/{model}:generateContent"
        headers = {"x-goog-api-key": self._api_key or "", "Content-Type": "application/json"}
        body = self._body(model, system, prompt, json_schema, temperature)
        try:
            resp = await self._client.post(url, json=body, headers=headers)
        except httpx.TransportError as exc:
            raise Overloaded(type(exc).__name__) from exc

        if resp.status_code == 200:
            return self._parse(resp.json())
        error = _error_payload(resp)
        msg = f"{resp.status_code}: {str(error.get('message', ''))[:200]}"
        if resp.status_code == 429:
            raise RateLimited(msg, daily=_is_daily(error), retry_after=_retry_delay(error))
        if resp.status_code >= 500:
            raise Overloaded(msg)
        if resp.status_code == 404:
            raise ModelMissing(msg)
        if resp.status_code == 401 or "API key" in msg:
            raise AuthFailed(msg)
        # Other 403s (region, model access) are route-specific: fall through to BadRequest.
        raise BadRequest(msg)

    @staticmethod
    def _parse(payload: dict[str, Any]) -> Completion:
        if block := payload.get("promptFeedback", {}).get("blockReason"):
            raise InvalidOutput(f"prompt blocked: {block}")
        candidates = payload.get("candidates") or []
        if not candidates:
            raise InvalidOutput("no candidates")
        cand = candidates[0]
        if (reason := cand.get("finishReason")) in _BAD_FINISH:
            raise InvalidOutput(f"finish reason {reason}")
        parts = cand.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise InvalidOutput("empty text")
        usage = payload.get("usageMetadata", {})
        return Completion(
            text=text,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
        )


_UNSUPPORTED_KEYS = {"maxItems", "minItems"}


def _gemini_compatible(node: Any) -> Any:
    """Gemini rejects maxItems/minItems; Pydantic still enforces them on the response."""
    if isinstance(node, dict):
        return {k: _gemini_compatible(v) for k, v in node.items() if k not in _UNSUPPORTED_KEYS}
    if isinstance(node, list):
        return [_gemini_compatible(v) for v in node]
    return node


def _error_payload(resp: httpx.Response) -> dict[str, Any]:
    try:
        err = resp.json().get("error", {})
        return err if isinstance(err, dict) else {}
    except ValueError:
        return {"message": resp.text[:200]}


def _is_daily(error: dict[str, Any]) -> bool:
    for detail in error.get("details", []):
        for v in detail.get("violations", []):
            if "PerDay" in str(v.get("quotaId", "")):
                return True
    return False


def _retry_delay(error: dict[str, Any]) -> float | None:
    for detail in error.get("details", []):
        if m := _DURATION.match(str(detail.get("retryDelay", ""))):
            return float(m.group(1))
    return None
