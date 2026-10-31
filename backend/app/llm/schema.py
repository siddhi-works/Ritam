import json
import re
from typing import Any

from pydantic import BaseModel

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def to_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON Schema with every $ref inlined.

    Provider support for $ref/$defs is uneven (Gemini, Groq, Mistral differ), so we resolve
    references ourselves and send one flat schema everywhere.
    """
    schema = model.model_json_schema()
    defs: dict[str, Any] = schema.pop("$defs", {})

    def resolve(node: Any, seen: frozenset[str]) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name in seen:
                    raise ValueError(f"recursive schema not supported: {name}")
                merged = {**defs[name], **{k: v for k, v in node.items() if k != "$ref"}}
                return resolve(merged, seen | {name})
            return {k: resolve(v, seen) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v, seen) for v in node]
        return node

    resolved: dict[str, Any] = resolve(schema, frozenset())
    return resolved


def schema_instruction(json_schema: dict[str, Any]) -> str:
    """For models without native schema support: the schema goes into the prompt instead."""
    return (
        "Respond with a single JSON object only, no prose and no code fences. "
        f"It must validate against this JSON Schema:\n{json.dumps(json_schema)}"
    )


def strip_fences(text: str) -> str:
    m = _FENCE.match(text)
    return m.group(1) if m else text.strip()
