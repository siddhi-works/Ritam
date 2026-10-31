"""Plain data for the rule engine, independent of the ORM and the LLM."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

Label = Literal["sourced", "ai_suggestion", "uncertain"]
Action = Literal["check_page", "call_bank", "grievance", "ombudsman"]

ISSUER_KINDS = {"official_page", "mitc_pdf", "kfs_pdf", "bank_notice"}
TERMS_KINDS = {"mitc_pdf", "kfs_pdf"}


@dataclass(frozen=True)
class SourceFact:
    id: str
    kind: str
    tier: int  # 1 = issuer/regulator, 4 = hearsay
    title: str
    url: str | None = None
    publisher: str | None = None
    published_at: date | None = None
    effective_from: date | None = None
    announced_at: date | None = None
    date_confidence: float | None = None
    observed_at: date | None = None  # fetched, or the Wayback snapshot date
    archived: bool = False
    redirected_to: str | None = None
    said_at: date | None = None
    pages: tuple[str, ...] = ()  # page texts, for the absence check and copy detection

    @property
    def is_issuer(self) -> bool:
        return self.kind in ISSUER_KINDS

    @property
    def best_date(self) -> date | None:
        return self.effective_from or self.published_at or self.announced_at


@dataclass(frozen=True)
class ClaimFact:
    id: str
    source_id: str
    attribute: str
    value_raw: str
    value_norm: dict[str, Any] | None
    quote: str
    page_no: int | None = None
    conditions: str | None = None
    valid_from: date | None = None


@dataclass(frozen=True)
class SubQuestion:
    text: str
    attributes: tuple[str, ...]


@dataclass
class Finding:
    type: str  # gap | unanswered | conflict | stale | undated | notice | mitc_missing | chat_mismatch | single_origin
    rule_id: str
    label: Label
    severity: int
    confidence: float
    title: str
    detail: dict[str, Any] = field(default_factory=dict)
    claim_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    subtype: str | None = None
    attribute: str | None = None
    key: str = ""  # stable id within an audit, e.g. "conflict:annual_fee"
