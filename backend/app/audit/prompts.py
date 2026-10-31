"""Planner and summary prompts, each with a deterministic fallback."""

import json
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, create_model

from app.analysis.facts import Finding, SubQuestion
from app.packs import Pack

PLAN_SYSTEM = """You plan an evidence audit of {subject} for a consumer.
Given the user's question, choose which attributes must be checked and split the question
into at most 6 concrete sub-questions, each tied to the attribute keys that would answer it.
Use only the attribute keys provided. Do not answer the question."""

EXPLAIN_SYSTEM = """You write a short, plain-English summary of an audit for a consumer.
Use ONLY the findings JSON given. Every sentence must cite at least one finding key in square
brackets, e.g. [conflict:annual_fee]. Do not add facts, numbers or dates that are not in the JSON.
Findings are possible signals, not verdicts: say "may", "possible", "not found in the sources
reviewed". For findings labelled "uncertain" say the point is unclear or needs checking, never that
something is missing. Mention only the most important findings. Never say "violation", "illegal"
or "fraud". At most 120 words."""


def plan_system(pack: Pack) -> str:
    return PLAN_SYSTEM.format(subject=pack.subject)


class Summary(BaseModel):
    summary: str = Field(max_length=1200)


def plan_schema(pack: Pack) -> type[BaseModel]:
    attr = Enum("PlanAttribute", {k: k for k in pack.keys}, type=str)  # type: ignore[misc]
    sub = create_model(
        "SubQuestionOut",
        text=(str, Field(min_length=3, max_length=200)),
        attributes=(list[attr], Field(max_length=4)),
    )
    model: type[BaseModel] = create_model(
        "Plan",
        attributes=(list[attr], Field(max_length=12)),
        sub_questions=(list[sub], Field(max_length=6)),
    )
    return model


def plan_prompt(pack: Pack, question: str) -> str:
    attrs = "\n".join(f"- {a.key}: {a.label}" for a in pack.attributes)
    return f"Attribute keys:\n{attrs}\n\nUser question:\n<question>{question[:1000]}</question>"


def parse_plan(data: BaseModel) -> tuple[list[str], list[SubQuestion]]:
    raw = data.model_dump(mode="json")
    attrs = [a.value if isinstance(a, Enum) else a for a in raw["attributes"]]
    subs = [
        SubQuestion(
            s["text"], tuple(a.value if isinstance(a, Enum) else a for a in s["attributes"])
        )
        for s in raw["sub_questions"]
    ]
    return attrs, subs


def fallback_plan(pack: Pack) -> tuple[list[str], list[SubQuestion]]:
    return [a.key for a in pack.attributes if a.importance >= 4], []


def findings_json(findings: list[Finding]) -> str:
    slim = [
        {"key": f.key, "type": f.type, "label": f.label, "severity": f.severity, "title": f.title}
        for f in sorted(findings, key=lambda f: (-f.severity, -f.confidence))[:12]
    ]
    return json.dumps(slim, ensure_ascii=False)


_CITE = re.compile(r"\[([a-z_]+:[^\]]+)\]")
_NUMERAL = re.compile(r"\d[\d,.]*")


def validate_summary(text: str, findings: list[Finding]) -> list[str]:
    """Problems with an LLM summary; empty means accept. Every cited key must exist and every
    numeral must appear in the findings it was given."""
    problems = []
    keys = {f.key for f in findings}
    cited = set(_CITE.findall(text))
    if not cited:
        problems.append("no finding cited")
    if cited - keys:
        problems.append(f"unknown keys: {sorted(cited - keys)[:3]}")
    source_text = findings_json(findings)
    for num in _NUMERAL.findall(_CITE.sub("", text)):
        if num.strip(".,") not in source_text:
            problems.append(f"numeral not in findings: {num}")
    if len(text.split()) > 150:
        problems.append("too long")
    lowered = text.lower()
    if any(w in lowered for w in ("violation", "illegal", "fraud")):
        problems.append("verdict wording")
    return problems


def fallback_summary(findings: list[Finding]) -> str:
    if not findings:
        return "No potential gaps, conflicts or outdated information were found in the sources reviewed."
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.type] = counts.get(f.type, 0) + 1
    names = {
        "conflict": "possible conflicts", "stale": "possibly outdated items", "notice": "notice-period signals",
        "mitc_missing": "required terms not found", "unanswered": "unanswered questions",
        "undated": "undated sources", "chat_mismatch": "differences from what customer care said",
        "single_origin": "single-origin claims",
    }  # fmt: skip
    parts = [f"{n} {names.get(t, t)}" for t, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    top = max(findings, key=lambda f: f.severity)
    return f"Found {', '.join(parts)}. Most important: {top.title} [{top.key}]."


def summary_payload(text: str, *, source: str, problems: list[str] | None = None) -> dict[str, Any]:
    return {"text": text, "generated_by": source, "label": "ai_suggestion" if source != "template" else "sourced",
            "validation_problems": problems or []}  # fmt: skip
