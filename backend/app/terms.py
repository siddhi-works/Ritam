"""Versioned card terms: every checked value of every card attribute, dated, so Ritam can say which
terms applied on any day ("when I got the card" vs "now") and what changed in between.

Only the bank's own documents (and RBI's) decide what was in force; comparison sites lag and are
never used here. A value's date is the date the document says it takes effect, else the
document's own date. Built from claims already stored by reports; no extra AI calls."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.compare import comparable, same_value
from app.extract.prompt import scope_key
from app.models import Audit, AuditSource, Claim, Source, SourceKind
from app.packs import load_pack
from app.reports import public_report

OFFICIAL_KINDS = {
    SourceKind.OFFICIAL_PAGE,
    SourceKind.MITC_PDF,
    SourceKind.KFS_PDF,
    SourceKind.BANK_NOTICE,
    SourceKind.RBI_RULE,
}


@dataclass(frozen=True)
class TermVersion:
    attribute: str
    value: str
    norm: dict[str, Any] | None
    effective_from: date | None  # stated in the document
    dated: date | None  # effective date, else the document's own date, else when Ritam read it
    dated_by: str  # "effective" | "document" | "read": how sure the date is
    quote: str
    source_url: str | None
    source_title: str | None
    claim_id: str
    source_kind: str = ""
    read_on: date | None = None  # when Ritam last fetched the document

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "dated": self.dated.isoformat() if self.dated else None,
            "dated_by": self.dated_by,
            "quote": self.quote,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "claim_id": self.claim_id,
        }


_ZERO = re.compile(
    r"^\W*(nil|free|zero|waived|not applicable|no\b.*\b(fee|charge)s?)\W*$"
    r"|^\W*(rs\.?|inr|₹)?\s*0+(\.0+)?\W*$",
    re.I,
)


def _is_zero(v: TermVersion) -> bool:
    return bool((v.norm or {}).get("value") == 0 or _ZERO.match(v.value.strip()))


def same(a: TermVersion, b: TermVersion) -> bool:
    """Equal values; unparsed text counts as equal only when written the same way. "Nil", "free"
    and "no annual fee" all mean zero."""
    if _is_zero(a) and _is_zero(b):
        return True
    if comparable(a.norm, b.norm):
        return same_value(a.norm, b.norm)  # type: ignore[arg-type]
    return " ".join(a.value.lower().split()) == " ".join(b.value.lower().split())


@dataclass(frozen=True)
class Snapshot:
    """Every value of one attribute dated the same day: fee slabs, a list of exclusions, or two
    documents that disagree. Values on the same day never count as a change."""

    dated: date
    dated_by: str
    values: tuple[TermVersion, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dated": self.dated.isoformat(),
            "dated_by": self.dated_by,
            "values": [v.as_dict() for v in self.values],
        }


def same_set(a: Snapshot, b: Snapshot) -> bool:
    return all(any(same(x, y) for y in b.values) for x in a.values) and all(
        any(same(y, x) for x in a.values) for y in b.values
    )


def certain(a: Snapshot, b: Snapshot) -> bool:
    """Every value on both sides parsed to a number of the same kind, so a difference is a real
    change. Free text (reward rules, exclusions) can only be "worded differently"."""
    return all(comparable(x.norm, y.norm) for x in a.values for y in b.values) and bool(
        a.values and b.values
    )


_SURE = {"effective": 0, "document": 1, "read": 2}


def timeline(versions: list[TermVersion]) -> list[Snapshot]:
    """One snapshot per date, oldest first; a snapshot equal to the one before is dropped, so only
    real moves remain. Undated versions can't be placed in time and are left out."""
    by_day: dict[date, list[TermVersion]] = {}
    for v in versions:
        if v.dated:
            by_day.setdefault(v.dated, []).append(v)
    out: list[Snapshot] = []
    for day in sorted(by_day):
        vs: list[TermVersion] = []
        for v in by_day[day]:  # the same value from several documents is shown once
            if not any(same(v, w) for w in vs):
                vs.append(v)
        snap = Snapshot(day, min((v.dated_by for v in vs), key=_SURE.__getitem__), tuple(vs))
        if not out or not same_set(out[-1], snap):
            out.append(snap)
    return out


def in_force(versions: list[TermVersion], on: date) -> Snapshot | None:
    """The values in force on `on`: the latest dated snapshot on or before that day."""
    before = [s for s in timeline(versions) if s.dated <= on]
    return before[-1] if before else None


@dataclass(frozen=True)
class TermChange:
    attribute: str
    before: Snapshot
    after: Snapshot

    def as_dict(self) -> dict[str, Any]:
        return {
            "attribute": self.attribute,
            "certain": certain(self.before, self.after),
            "before": self.before.as_dict(),
            "after": self.after.as_dict(),
            "from": self.after.dated.isoformat(),
        }


def changes_between(
    by_attr: dict[str, list[TermVersion]], start: date, end: date
) -> list[TermChange]:
    """Every change that took effect after `start` and on or before `end`."""
    out: list[TermChange] = []
    for attr, versions in by_attr.items():
        line = timeline(versions)
        for prev, nxt in zip(line, line[1:], strict=False):
            # A change needs a real date on the newer value; "when Ritam read it" is not one.
            if nxt.dated_by != "read" and start < nxt.dated <= end:
                out.append(TermChange(attr, prev, nxt))
    return sorted(out, key=lambda c: c.after.dated)


def then_vs_now(
    by_attr: dict[str, list[TermVersion]], then: date, now: date
) -> list[dict[str, Any]]:
    rows = []
    for attr in sorted(by_attr):
        a, b = in_force(by_attr[attr], then), in_force(by_attr[attr], now)
        if a is None and b is None:
            continue
        differs = bool(a and b and not same_set(a, b))
        rows.append(
            {
                "attribute": attr,
                "then": a.as_dict() if a else None,
                "now": b.as_dict() if b else None,
                # True: the numbers changed. "maybe": worded differently, check the quotes. False: same.
                "changed": differs if not differs or (a and b and certain(a, b)) else "maybe",
            }
        )
    return rows


async def load_terms(session: AsyncSession, card_name: str) -> dict[str, list[TermVersion]]:
    """Every verified value from the bank's own documents, across all public reports on the card.
    Reports that include a user's chat or upload stay private and are skipped."""
    pack = load_pack("credit_card")
    audits = select(Audit.id).where(*public_report(card_name)).scalar_subquery()
    rows = await session.execute(
        select(Claim, Source)
        .join(Source, Source.id == Claim.source_id)
        .join(AuditSource, AuditSource.source_id == Source.id)
        .where(
            AuditSource.audit_id.in_(audits),
            Claim.verified.is_(True),
            Claim.prompt_version.in_(
                [
                    scope_key(card_name, v)
                    for v in (pack.prompt_version, *pack.previous_prompt_versions)
                ]
            ),
            Source.kind.in_(OFFICIAL_KINDS),
        )
        .distinct()
    )
    out: dict[str, list[TermVersion]] = {}
    for claim, src in rows.tuples():
        eff = claim.valid_from or src.effective_from
        doc_date = src.published_at or src.announced_at
        read_on = src.fetched_at.date() if src.fetched_at else None
        dated_by = "effective" if eff else "document" if doc_date else "read"
        out.setdefault(claim.attribute_key, []).append(
            TermVersion(
                attribute=claim.attribute_key,
                value=claim.value_raw,
                norm=claim.value_norm,
                effective_from=eff,
                dated=eff or doc_date or read_on,
                dated_by=dated_by,
                quote=claim.quote,
                source_url=src.url,
                source_title=src.title,
                source_kind=src.kind.value,
                read_on=read_on,
                claim_id=str(claim.id),
            )
        )
    return out
