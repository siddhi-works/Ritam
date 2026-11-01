"""Postgres schema. Claims are bitemporal: valid_from/valid_to is when a term applies, observed_at
is when we saw it."""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


class SourceKind(enum.StrEnum):
    OFFICIAL_PAGE = "official_page"
    MITC_PDF = "mitc_pdf"
    KFS_PDF = "kfs_pdf"
    BANK_NOTICE = "bank_notice"
    RBI_RULE = "rbi_rule"
    AGGREGATOR = "aggregator"
    NEWS = "news"
    FORUM = "forum"
    USER_CHAT = "user_chat"
    USER_UPLOAD = "user_upload"


class SourceStatus(enum.StrEnum):
    PENDING = "pending"
    FETCHED = "fetched"
    PARSED = "parsed"
    EXTRACTED = "extracted"
    FAILED = "failed"


class AuditStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class FindingType(enum.StrEnum):
    GAP = "gap"
    UNANSWERED = "unanswered"
    CONFLICT = "conflict"
    STALE = "stale"
    UNDATED = "undated"
    NOTICE = "notice"
    MITC_MISSING = "mitc_missing"
    CHAT_MISMATCH = "chat_mismatch"
    SINGLE_ORIGIN = "single_origin"


class FindingLabel(enum.StrEnum):
    SOURCED = "sourced"
    AI_SUGGESTION = "ai_suggestion"
    UNCERTAIN = "uncertain"


class ChecklistAction(enum.StrEnum):
    CHECK_PAGE = "check_page"
    CALL_BANK = "call_bank"
    GRIEVANCE = "grievance"
    OMBUDSMAN = "ombudsman"


class Bank(Base):
    __tablename__ = "bank"
    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    grievance_url: Mapped[str | None] = mapped_column(Text)
    nodal_officer_url: Mapped[str | None] = mapped_column(Text)


class Product(Base):
    __tablename__ = "product"
    id: Mapped[uuid.UUID] = _uuid_pk()
    bank_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank.id", ondelete="CASCADE"))
    pack: Mapped[str] = mapped_column(String(32), default="credit_card")
    slug: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    network: Mapped[str | None] = mapped_column(String(32))
    variant: Mapped[str | None] = mapped_column(String(64))


class Attribute(Base):
    __tablename__ = "attribute"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    pack: Mapped[str] = mapped_column(String(32), default="credit_card")
    label: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(64))
    unit: Mapped[str | None] = mapped_column(String(32))
    importance: Mapped[int] = mapped_column(SmallInteger)
    mitc_required: Mapped[bool] = mapped_column(Boolean, default=False)
    rbi_ref: Mapped[str | None] = mapped_column(Text)


class Source(Base):
    __tablename__ = "source"
    __table_args__ = (Index("ix_source_content_hash", "content_hash"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[SourceKind] = mapped_column(_enum(SourceKind, "source_kind"))
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(200))
    authority_tier: Mapped[int] = mapped_column(SmallInteger, default=4)  # 1 = issuer/regulator
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product.id"))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[date | None] = mapped_column(Date)
    effective_from: Mapped[date | None] = mapped_column(Date)
    announced_at: Mapped[date | None] = mapped_column(Date)
    date_method: Mapped[str | None] = mapped_column(String(32))
    date_confidence: Mapped[float | None] = mapped_column(Float)
    raw_path: Mapped[str | None] = mapped_column(Text)
    fetch_method: Mapped[str | None] = mapped_column(String(32))  # httpx|browser|wayback|upload
    # Set only for Wayback copies: the snapshot time, so an old copy is never treated as current.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    said_at: Mapped[date | None] = mapped_column(Date)  # user_chat: when customer care said it
    doc_type: Mapped[str | None] = mapped_column(String(8))  # pdf|html|text
    page_count: Mapped[int | None] = mapped_column(Integer)
    # Date candidates, parse warnings, fetch attempts: evidence for the source viewer.
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus, "source_status"), default=SourceStatus.PENDING
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourcePage(Base):
    __tablename__ = "source_page"
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="CASCADE"), primary_key=True
    )
    page_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[uuid.UUID] = _uuid_pk()
    question: Mapped[str] = mapped_column(Text)
    # The card being audited; scopes extraction for multi-card documents (e.g. a bank-wide MITC).
    product_name: Mapped[str | None] = mapped_column(String(200))
    # Attribute pack the audit runs with (packs/<name>.yaml).
    pack: Mapped[str] = mapped_column(
        String(40), default="credit_card", server_default="credit_card"
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product.id"))
    status: Mapped[AuditStatus] = mapped_column(
        _enum(AuditStatus, "audit_status"), default=AuditStatus.QUEUED
    )
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditSource(Base):
    __tablename__ = "audit_source"
    audit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("audit.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="CASCADE"), primary_key=True
    )


class Claim(Base):
    __tablename__ = "claim"
    __table_args__ = (Index("ix_claim_product_attr", "product_id", "attribute_key"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product.id"))
    attribute_key: Mapped[str] = mapped_column(ForeignKey("attribute.key"))
    value_raw: Mapped[str] = mapped_column(Text)
    value_norm: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    conditions: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text)
    page_no: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    match_score: Mapped[float | None] = mapped_column(Float)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Why an unverified claim was dropped (quote_not_found | numbers_not_in_quote | ...). Kept so
    # the audit trace can show what the model claimed and why code rejected it.
    drop_reason: Mapped[str | None] = mapped_column(String(32))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    said_at: Mapped[date | None] = mapped_column(Date)  # user_chat claims only
    extractor: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))


class ExtractionCache(Base):
    """Keyed by (content_hash, chunk_index, prompt_version, model): re-audits cost nothing."""

    __tablename__ = "extraction_cache"
    __table_args__ = (UniqueConstraint("content_hash", "chunk_index", "prompt_version", "model"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_index: Mapped[int] = mapped_column(Integer)
    prompt_version: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    output: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Finding(Base):
    __tablename__ = "finding"
    id: Mapped[uuid.UUID] = _uuid_pk()
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.id", ondelete="CASCADE"))
    type: Mapped[FindingType] = mapped_column(_enum(FindingType, "finding_type"))
    subtype: Mapped[str | None] = mapped_column(String(32))
    severity: Mapped[int] = mapped_column(SmallInteger)
    confidence: Mapped[float] = mapped_column(Float)
    label: Mapped[FindingLabel] = mapped_column(_enum(FindingLabel, "finding_label"))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    claim_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    source_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    rule_id: Mapped[str] = mapped_column(String(64))


class ChecklistItem(Base):
    __tablename__ = "checklist_item"
    id: Mapped[uuid.UUID] = _uuid_pk()
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audit.id", ondelete="CASCADE"))
    rank: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text)
    finding_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    verify_url: Mapped[str | None] = mapped_column(Text)
    action: Mapped[ChecklistAction] = mapped_column(_enum(ChecklistAction, "checklist_action"))


class LlmUsage(Base):
    """Free-tier LLM calls per provider per quota day (midnight Pacific)."""

    __tablename__ = "llm_usage"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalCase(Base):
    __tablename__ = "eval_case"
    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(String(32))
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    expected: Mapped[dict[str, Any]] = mapped_column(JSONB)


class EvalRun(Base):
    __tablename__ = "eval_run"
    id: Mapped[uuid.UUID] = _uuid_pk()
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
