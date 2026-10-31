import json
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.llm.base import (
    AuthFailed,
    BadRequest,
    InvalidOutput,
    ModelMissing,
    Overloaded,
    RateLimited,
)
from app.llm.gemini import GeminiAdapter
from app.llm.openai_compat import OpenAICompatAdapter
from app.llm.schema import strip_fences, to_json_schema

G = "https://gen.test/v1beta"
OAI = "https://oai.test/v1"
SCHEMA = {"type": "object", "properties": {"v": {"type": "string"}}, "required": ["v"]}


class Inner(BaseModel):
    value: str
    quote: str


class Wrapper(BaseModel):
    claims: list[Inner]


def kwargs(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "system": "SYS",
        "prompt": "USER",
        "json_schema": SCHEMA,
        "schema_name": "Fee",
        "temperature": 0.0,
    }


def gemini_ok(text: str, thought: bool = False) -> httpx.Response:
    parts: list[dict[str, Any]] = [{"text": text}]
    if thought:
        parts.insert(0, {"text": "thinking", "thought": True})
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"parts": parts}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7},
        },
    )


def gemini_err(status: int, msg: str = "x", details: list[Any] | None = None) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": msg, "details": details or []}})


# Gemini


@respx.mock
async def test_gemini_native_schema_header_key_and_thought_parts_skipped() -> None:
    route = respx.post(f"{G}/models/gemini-x:generateContent").mock(
        return_value=gemini_ok('{"v": "1"}', thought=True)
    )
    async with httpx.AsyncClient() as c:
        out = await GeminiAdapter("KEY", base_url=G, client=c).complete_json(**kwargs("gemini-x"))
    assert (out.text, out.input_tokens, out.output_tokens) == ('{"v": "1"}', 11, 7)
    req = route.calls.last.request
    body = json.loads(req.content)
    assert req.headers["x-goog-api-key"] == "KEY" and "KEY" not in str(req.url)
    assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert body["generationConfig"]["responseJsonSchema"] == SCHEMA


@respx.mock
async def test_gemma_gets_system_and_schema_folded_into_prompt() -> None:
    route = respx.post(f"{G}/models/gemma-4-31b-it:generateContent").mock(
        return_value=gemini_ok('{"v": "1"}')
    )
    async with httpx.AsyncClient() as c:
        await GeminiAdapter("K", base_url=G, client=c).complete_json(**kwargs("gemma-4-31b-it"))
    body = json.loads(route.calls.last.request.content)
    assert "systemInstruction" not in body
    assert "responseJsonSchema" not in body["generationConfig"]
    text = body["contents"][0]["parts"][0]["text"]
    assert text.startswith("SYS") and '"required": ["v"]' in text and text.endswith("USER")


@pytest.mark.parametrize(
    ("resp", "exc"),
    [
        (
            gemini_err(429, details=[{"violations": [{"quotaId": "RequestsPerDayPerModel"}]}]),
            RateLimited,
        ),
        (gemini_err(503), Overloaded),
        (gemini_err(404), ModelMissing),
        (gemini_err(400, "API key not valid. Please pass a valid API key."), AuthFailed),
        (gemini_err(400, "Invalid JSON payload"), BadRequest),
        (httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY"}]}), InvalidOutput),
    ],
)
@respx.mock
async def test_gemini_error_classification(resp: httpx.Response, exc: type[Exception]) -> None:
    respx.post(f"{G}/models/m:generateContent").mock(return_value=resp)
    async with httpx.AsyncClient() as c:
        with pytest.raises(exc):
            await GeminiAdapter("K", base_url=G, client=c).complete_json(**kwargs("m"))


@respx.mock
async def test_gemini_429_daily_flag_and_retry_delay() -> None:
    minute = gemini_err(429, details=[{"retryDelay": "7s"}])
    respx.post(f"{G}/models/m:generateContent").mock(return_value=minute)
    async with httpx.AsyncClient() as c:
        with pytest.raises(RateLimited) as e:
            await GeminiAdapter("K", base_url=G, client=c).complete_json(**kwargs("m"))
    assert e.value.daily is False and e.value.retry_after == 7.0


# OpenAI-compatible


def oai_ok(content: str, finish: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 4},
        },
    )


def oai_err(status: int, msg: str, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": msg}}, headers=headers)


def adapter(c: httpx.AsyncClient) -> OpenAICompatAdapter:
    return OpenAICompatAdapter("groq", "GK", base_url=OAI, client=c, extra_headers={"X-Title": "R"})


@respx.mock
async def test_openai_compat_sends_json_schema_and_bearer_key() -> None:
    route = respx.post(f"{OAI}/chat/completions").mock(return_value=oai_ok('{"v": "1"}'))
    async with httpx.AsyncClient() as c:
        out = await adapter(c).complete_json(**kwargs("openai/gpt-oss-120b"))
    assert (out.text, out.input_tokens, out.output_tokens) == ('{"v": "1"}', 9, 4)
    req = route.calls.last.request
    body = json.loads(req.content)
    assert req.headers["authorization"] == "Bearer GK" and req.headers["x-title"] == "R"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert body["messages"][0] == {"role": "system", "content": "SYS"}


@respx.mock
async def test_openai_compat_downgrades_to_json_object_once_per_model() -> None:
    route = respx.post(f"{OAI}/chat/completions").mock(
        side_effect=[
            oai_err(400, "response_format json_schema is not supported by this model"),
            oai_ok('{"v": "1"}'),
            oai_ok('{"v": "2"}'),
        ]
    )
    async with httpx.AsyncClient() as c:
        a = adapter(c)
        await a.complete_json(**kwargs("old-model"))
        await a.complete_json(**kwargs("old-model"))
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert [b["response_format"]["type"] for b in bodies] == [
        "json_schema",
        "json_object",
        "json_object",
    ]
    assert '"required": ["v"]' in bodies[1]["messages"][0]["content"]


@pytest.mark.parametrize(
    ("resp", "exc", "daily"),
    [
        (
            oai_err(429, "Rate limit reached on tokens per day (TPD): Limit 200000"),
            RateLimited,
            True,
        ),
        (oai_err(429, "Rate limit exceeded: free-models-per-day"), RateLimited, True),
        (
            oai_err(429, "Rate limit reached on requests per minute", {"retry-after": "2"}),
            RateLimited,
            False,
        ),
        (oai_err(500, "boom"), Overloaded, None),
        (oai_err(404, "model not found"), ModelMissing, None),
        (oai_err(401, "invalid api key"), AuthFailed, None),
        (oai_err(413, "Request too large for model"), BadRequest, None),
        (oai_ok('{"v": "1', finish="length"), InvalidOutput, None),
    ],
)
@respx.mock
async def test_openai_compat_error_classification(
    resp: httpx.Response, exc: type[Exception], daily: bool | None
) -> None:
    respx.post(f"{OAI}/chat/completions").mock(return_value=resp)
    async with httpx.AsyncClient() as c:
        with pytest.raises(exc) as e:
            await adapter(c).complete_json(**kwargs("m"))
    if daily is not None:
        assert isinstance(e.value, RateLimited) and e.value.daily is daily
        if not daily:
            assert e.value.retry_after == 2.0


# schema helpers


def test_schema_refs_are_inlined() -> None:
    schema = to_json_schema(Wrapper)
    assert "$defs" not in json.dumps(schema) and "$ref" not in json.dumps(schema)
    assert schema["properties"]["claims"]["items"]["required"] == ["value", "quote"]


def test_strip_fences() -> None:
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('  {"a": 1} ') == '{"a": 1}'


# Provider quirks seen in live tests


@respx.mock
async def test_mistral_top_level_error_message_and_zero_limit_skips_model() -> None:
    respx.post(f"{OAI}/chat/completions").mock(
        return_value=httpx.Response(
            429,
            json={"object": "error", "message": "Rate limit exceeded", "type": "rate_limited"},
            headers={"x-ratelimit-limit-req-minute": "0"},
        )
    )
    async with httpx.AsyncClient() as c:
        with pytest.raises(ModelMissing) as e:
            await adapter(c).complete_json(**kwargs("mistral-small-latest"))
    assert "Rate limit exceeded" in str(e.value)


@respx.mock
async def test_openrouter_model_specific_403_is_not_an_auth_failure() -> None:
    respx.post(f"{OAI}/chat/completions").mock(
        return_value=oai_err(403, "only available on agentic harnesses")
    )
    async with httpx.AsyncClient() as c:
        with pytest.raises(BadRequest):
            await adapter(c).complete_json(**kwargs("thinkingmachines/inkling:free"))


@respx.mock
async def test_reasoning_model_list_content_keeps_only_text_parts() -> None:
    content = [
        {"type": "thinking", "thinking": [{"type": "text", "text": "hmm"}]},
        {"type": "text", "text": '{"v": "1"}'},
    ]
    route = respx.post(f"{OAI}/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
        )
    )
    async with httpx.AsyncClient() as c:
        out = await adapter(c).complete_json(**kwargs("mistral-large-4"))
    assert out.text == '{"v": "1"}'
    assert json.loads(route.calls.last.request.content)["top_p"] == 1


@respx.mock
async def test_gemini_schema_drops_unsupported_array_limits() -> None:
    route = respx.post(f"{G}/models/gemini-x:generateContent").mock(
        return_value=gemini_ok('{"v": "1"}')
    )
    schema = {
        "type": "object",
        "properties": {
            "v": {"type": "array", "maxItems": 6, "minItems": 1, "items": {"type": "string"}}
        },
    }
    async with httpx.AsyncClient() as c:
        await GeminiAdapter("K", base_url=G, client=c).complete_json(
            **{**kwargs("gemini-x"), "json_schema": schema}
        )
    sent = json.loads(route.calls.last.request.content)["generationConfig"]["responseJsonSchema"]
    assert "maxItems" not in json.dumps(sent) and "minItems" not in json.dumps(sent)
