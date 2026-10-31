"""Ranked "verify next" checklist built from findings."""

from dataclasses import dataclass

from app.analysis.facts import Action, Finding, SourceFact
from app.packs import Pack

_TYPE_WEIGHT = {
    "notice": 4,  # a passing notice check has severity 1, so it still ranks low
    "chat_mismatch": 4,
    "conflict": 3,
    "stale": 2,
    "mitc_missing": 2,
    "unanswered": 1,
    "undated": 1,
    "single_origin": 0,
}
_ACTION_ORDER: dict[Action, int] = {"grievance": 0, "call_bank": 1, "check_page": 2, "ombudsman": 3}
_LABEL_WEIGHT = {"sourced": 2, "uncertain": 1, "ai_suggestion": 0}


@dataclass
class ChecklistEntry:
    rank: int
    text: str
    why: str
    finding_keys: list[str]
    verify_url: str | None
    action: Action
    priority: float


def _official_url(f: Finding, sources: dict[str, SourceFact]) -> str | None:
    for sid in f.source_ids:
        s = sources.get(sid)
        if s and s.is_issuer and s.url:
            return s.url
    for s in sources.values():
        if s.is_issuer and s.url and not s.redirected_to:
            return s.url
    return None


def _entry(
    f: Finding,
    sources: dict[str, SourceFact],
    labels: dict[str, str],
    issuer: str = "the bank",
    terms: str = "MITC",
) -> tuple[str, Action]:
    attr = f.detail.get("attribute") or f.attribute or ""
    label = (labels.get(attr) or attr.replace("_", " ") or "this term").lower()
    match f.type:
        case "notice" if f.subtype == "adequate":
            return (
                "Check the date you were actually told about this change (email/SMS); the published "
                "notice appears to give enough time, but your notice date is what counts.",
                "check_page",
            )
        case "notice":
            return ("Check the bank's notice and MITC: when was this change announced and when did it take "
                    "effect? If notice was short, ask the bank in writing and keep the reply."), "grievance"  # fmt: skip
        case "chat_mismatch":
            return (f"Ask {issuer} to confirm the {label} in writing; what you were told differs from "
                    "the terms valid on that date."), "call_bank"  # fmt: skip
        case "conflict" if f.subtype == "self":
            return (f"Ask {issuer} which of its own documents is correct for the {label} "
                    f"(web page vs {terms} or notice)."), "call_bank"  # fmt: skip
        case "conflict":
            return (
                f"Confirm the current {label} in {issuer}'s latest {terms}, not on third-party sites.",
                "check_page",
            )
        case "stale" if f.subtype == "redirect":
            return (
                f"Find {issuer}'s current page for this exact product; the old link now opens a "
                "different page, so don't rely on it or on sites that link to it.",
                "check_page",
            )
        case "stale":
            return (
                f"Ignore the outdated figure; confirm the {label} in {issuer}'s own latest {terms}.",
                "check_page",
            )
        case "mitc_missing":
            return (f"Find the {label} in the card's Most Important Terms and Conditions, or ask the bank "
                    "for it in writing."), "call_bank"  # fmt: skip
        case "unanswered":
            return f"Find an official answer to: {f.detail.get('question', label)}", "check_page"
        case "undated":
            return "Find the date of this document before relying on it.", "check_page"
        case _:
            return f"Verify the {label} with an independent official source.", "check_page"


def build_checklist(
    findings: list[Finding],
    sources: dict[str, SourceFact],
    *,
    limit: int = 12,
    labels: dict[str, str] | None = None,
    pack: Pack | None = None,
) -> list[ChecklistEntry]:
    issuer, terms = (pack.issuer, pack.terms_doc) if pack else ("the bank", "MITC")
    scored: list[tuple[float, int, ChecklistEntry]] = []
    seen_text: set[str] = set()
    for f in findings:
        text, action = _entry(f, sources, labels or {}, issuer, terms)
        if text in seen_text:  # one item per distinct action (e.g. several undated sources)
            continue
        seen_text.add(text)
        priority = (
            f.severity * 2 + _TYPE_WEIGHT.get(f.type, 0) + _LABEL_WEIGHT[f.label] + f.confidence
        )
        entry = ChecklistEntry(
            0, text, f.title, [f.key], _official_url(f, sources), action, round(priority, 2)
        )
        scored.append((-priority, _ACTION_ORDER[action], entry))
    scored.sort(key=lambda t: (t[0], t[1]))
    out = []
    for rank, (_, _, entry) in enumerate(scored[:limit], start=1):
        entry.rank = rank
        out.append(entry)
    return out


FORBIDDEN_WORDS = (
    "violation",
    "violates",
    "illegal",
    "fraud",
    "does not exist",
    "definitely",
    "guaranteed",
)
