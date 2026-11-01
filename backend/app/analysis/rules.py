"""Deterministic rules that turn claims into findings. Wording stays cautious: findings are signals,
not verdicts."""

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any

from rapidfuzz import fuzz

from app.analysis.absence import find_mentions
from app.analysis.compare import comparable, same_value
from app.analysis.facts import TERMS_KINDS, ClaimFact, Finding, SourceFact, SubQuestion
from app.packs import Pack

RBI_NOTICE_DAYS = 30  # RBI: one month's notice before charges change


# History notes ("previously 1.5%", "extended from 15 Oct") don't change who a value applies to.
_HISTORY = re.compile(
    r"^(previously|earlier|extended|revised|updated|changed|increased|reduced|was)\b"
)


def _words(s: str | None) -> str:
    return " ".join(re.sub(r"[^\w%.]+", " ", (s or "").lower()).split())


def _norm_cond(c: str | None, product: str | None = None) -> str:
    text = _words(c)
    if not text or _HISTORY.match(text):
        return ""
    if product and fuzz.token_set_ratio(text, _words(product)) >= 90:
        return ""  # just restates the audited product's name
    return text


class Analysis:
    def __init__(
        self,
        pack: Pack,
        sources: Iterable[SourceFact],
        claims: Iterable[ClaimFact],
        *,
        sub_questions: Iterable[SubQuestion] = (),
        today: date | None = None,
        product: str | None = None,
    ):
        self.pack = pack
        self.product = product
        self.sources = {s.id: s for s in sources}
        self.all_claims = list(claims)
        self.sub_questions = list(sub_questions)
        self.today = today or date.today()
        # Claims from a page that redirected to a different product, or from customer chats,
        # never take part in source-vs-source comparisons.
        self.comparable_claims = [
            c
            for c in self.all_claims
            if c.source_id in self.sources
            and not self.sources[c.source_id].redirected_to
            and self.sources[c.source_id].kind != "user_chat"
        ]

    def _importance(self, attribute: str) -> int:
        spec = self.pack.get(attribute)
        return spec.importance if spec else 2

    def _label(self, attribute: str) -> str:
        spec = self.pack.get(attribute)
        return spec.label if spec else attribute

    def _by_attr(self, claims: Iterable[ClaimFact]) -> dict[str, list[ClaimFact]]:
        out: dict[str, list[ClaimFact]] = defaultdict(list)
        for c in claims:
            out[c.attribute].append(c)
        return out

    def _evidence(self, c: ClaimFact) -> dict[str, Any]:
        s = self.sources[c.source_id]
        return {
            "claim_id": c.id,
            "source_id": s.id,
            "source": s.title,
            "kind": s.kind,
            "tier": s.tier,
            "value": c.value_raw,
            "quote": c.quote,
            "page_no": c.page_no,
            "conditions": c.conditions,
            "valid_from": c.valid_from.isoformat() if c.valid_from else None,
        }

    def _valid_from(self, c: ClaimFact) -> date | None:
        return c.valid_from or self.sources[c.source_id].effective_from

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        findings += self.undated()
        findings += self.redirected()
        conflicts, stale = self.conflicts_and_stale()
        findings += conflicts + stale
        findings += self.notice()
        findings += self.terms_missing()
        findings += self.unanswered()
        findings += self.chat_mismatch()
        return findings

    def undated(self) -> list[Finding]:
        out = []
        for s in self.sources.values():
            if s.kind == "user_chat":  # dated by when it was said, not by the text
                continue
            if s.date_confidence is not None and s.date_confidence >= 0.5:
                continue
            out.append(
                Finding(
                    type="undated",
                    rule_id="undated.source",
                    label="sourced",
                    severity=3 if s.is_issuer else 2,
                    confidence=0.9,
                    title=f"Undated source: no reliable date found in “{s.title}”",
                    detail={
                        "why": "Without a date you cannot tell whether these terms are current.",
                        "date_confidence": s.date_confidence,
                    },
                    source_ids=[s.id],
                    key=f"undated:{s.id}",
                )
            )
        return out

    def redirected(self) -> list[Finding]:
        out = []
        for s in self.sources.values():
            if not s.redirected_to:
                continue
            out.append(
                Finding(
                    type="stale",
                    subtype="redirect",
                    rule_id="stale.redirect",
                    label="uncertain",
                    severity=3,
                    confidence=0.8,
                    title=f"Possibly outdated link: “{s.title}” now opens a different page",
                    detail={
                        "requested_url": s.url,
                        "redirected_to": s.redirected_to,
                        "why": "Links to the old page (e.g. on comparison sites) may now show a "
                        "different product. Its claims were kept out of the comparison.",
                    },
                    source_ids=[s.id],
                    key=f"redirect:{s.id}",
                )
            )
        return out

    def conflicts_and_stale(self) -> tuple[list[Finding], list[Finding]]:
        conflicts: list[Finding] = []
        stale: list[Finding] = []
        for attribute, claims in self._by_attr(self.comparable_claims).items():
            per_source: dict[str, list[ClaimFact]] = defaultdict(list)
            for c in claims:
                if c.value_norm and c.value_norm.get("parsed"):
                    per_source[c.source_id].append(c)
            if len(per_source) < 2:
                continue

            issuer_ids = [sid for sid in per_source if self.sources[sid].is_issuer]
            current_issuer = self._current_issuer_claims(issuer_ids, per_source)

            # Stale: a lower-tier source disagrees with the issuer's current value that took
            # effect before that source was observed.
            stale_sources: set[str] = set()
            if current_issuer:
                effective = max(
                    filter(None, (self._valid_from(c) for c in current_issuer)), default=None
                )
                for sid, cs in per_source.items():
                    s = self.sources[sid]
                    if s.is_issuer or s.tier < 3:
                        continue
                    if self._sets_match(cs, current_issuer):
                        continue
                    # Outdated only if the source still shows an older issuer value; a value the issuer
                    # never published is a possible conflict instead.
                    if (
                        effective
                        and s.observed_at
                        and effective <= s.observed_at
                        and self._matches_older_issuer_value(attribute, cs, current_issuer)
                    ):
                        stale_sources.add(sid)
                        stale.append(
                            self._stale_finding(attribute, s, cs, current_issuer, effective)
                        )

            # Conflicts between the remaining sources, pairwise, unconditional values only.
            ids = sorted(sid for sid in per_source if sid not in stale_sources)
            pairs: list[tuple[str, str, str]] = []
            for i, a in enumerate(ids):
                for b in ids[i + 1 :]:
                    kind = self._pair_kind(per_source[a], per_source[b])
                    if kind:
                        pairs.append((a, b, kind))
            if pairs:
                conflicts.append(self._conflict_finding(attribute, per_source, pairs))
        return conflicts, stale

    def _current_issuer_claims(
        self, issuer_ids: list[str], per_source: dict[str, list[ClaimFact]]
    ) -> list[ClaimFact]:
        """The issuer's latest values: highest valid_from wins; undated values only if nothing
        dated exists."""
        claims = [c for sid in issuer_ids for c in per_source[sid]]
        dated = [c for c in claims if self._valid_from(c)]
        if not dated:
            return claims
        latest = max(d for c in dated if (d := self._valid_from(c)) is not None)
        return [c for c in dated if self._valid_from(c) == latest]

    @staticmethod
    def _sets_match(a: list[ClaimFact], b: list[ClaimFact]) -> bool:
        """Some value in `a` equals some value in `b` (slab tables list many values)."""
        return any(
            comparable(x.value_norm, y.value_norm) and same_value(x.value_norm, y.value_norm)  # type: ignore[arg-type]
            for x in a
            for y in b
        )

    def _matches_older_issuer_value(
        self, attribute: str, claims: list[ClaimFact], current: list[ClaimFact]
    ) -> bool:
        older = [
            c for c in self.comparable_claims
            if c.attribute == attribute and self.sources[c.source_id].is_issuer and c not in current
        ]  # fmt: skip
        return bool(older) and self._sets_match(claims, older)

    def _pair_kind(self, a: list[ClaimFact], b: list[ClaimFact]) -> str | None:
        if self._sets_match(a, b):
            return None
        if not any(comparable(x.value_norm, y.value_norm) for x in a for y in b):
            return None  # different value types: not evidence of a conflict
        conds_a = {_norm_cond(c.conditions, self.product) for c in a}
        conds_b = {_norm_cond(c.conditions, self.product) for c in b}
        if conds_a != conds_b and (conds_a - {""} or conds_b - {""}):
            return "scope"
        dates_a = {self._valid_from(c) for c in a} - {None}
        dates_b = {self._valid_from(c) for c in b} - {None}
        if dates_a and dates_b and dates_a.isdisjoint(dates_b):
            return "temporal"
        return "true"

    def _conflict_finding(
        self,
        attribute: str,
        per_source: dict[str, list[ClaimFact]],
        pairs: list[tuple[str, str, str]],
    ) -> Finding:
        kinds = {k for _, _, k in pairs}
        sources = sorted({sid for a, b, _ in pairs for sid in (a, b)})
        involved = [c for sid in sources for c in per_source[sid]]
        issuer_pairs = [
            (a, b) for a, b, k in pairs
            if k == "true" and self.sources[a].is_issuer and self.sources[b].is_issuer
        ]  # fmt: skip
        label = self._label(attribute)
        if issuer_pairs:
            subtype, verdict, conf = "self", "sourced", 0.85
            title = f"Possible conflict: {self.pack.issuer}'s own documents disagree on {label}"
            sev_bonus = 1
        elif "true" in kinds:
            subtype, verdict, conf = "true", "sourced", 0.8
            title = f"Possible conflict: sources give different values for {label}"
            sev_bonus = 0
        elif "temporal" in kinds:
            subtype, verdict, conf = "temporal", "sourced", 0.7
            title = f"{label} changed over time: sources quote values from different dates"
            sev_bonus = -1
        else:
            subtype, verdict, conf = "scope", "uncertain", 0.5
            title = f"Possible conflict on {label}, but the values have different conditions"
            sev_bonus = -1
        return Finding(
            type="conflict",
            subtype=subtype,
            rule_id=f"conflict.{subtype}",
            label=verdict,  # type: ignore[arg-type]
            severity=max(1, min(5, self._importance(attribute) + sev_bonus)),
            confidence=conf,
            title=title,
            detail={
                "attribute": attribute,
                "evidence": [self._evidence(c) for c in involved],
                "pairs": [{"a": a, "b": b, "kind": k} for a, b, k in pairs],
            },
            claim_ids=[c.id for c in involved],
            source_ids=sources,
            attribute=attribute,
            key=f"conflict:{attribute}",
        )

    def _stale_finding(
        self,
        attribute: str,
        s: SourceFact,
        claims: list[ClaimFact],
        current: list[ClaimFact],
        effective: date,
    ) -> Finding:
        days = (self.today - effective).days
        # Does the stale source match an *older* issuer value? Then it was probably never updated.
        older = [
            c for c in self.comparable_claims
            if c.attribute == attribute and self.sources[c.source_id].is_issuer and c not in current
        ]  # fmt: skip
        matches_old = self._sets_match(claims, older) if older else False
        title = (
            f"Possibly outdated: {s.title} shows an old {self._label(attribute)} "
            f"(stale since {effective:%d %b %Y}, {days} days)"
        )
        return Finding(
            type="stale",
            subtype="aggregator",
            rule_id="stale.aggregator",
            label="sourced",
            severity=max(1, min(5, self._importance(attribute))),
            confidence=0.85 if matches_old else 0.7,
            title=title,
            detail={
                "attribute": attribute,
                "stale_since": effective.isoformat(),
                "days_stale": days,
                "matches_older_issuer_value": matches_old,
                "stale": [self._evidence(c) for c in claims],
                "current": [self._evidence(c) for c in current],
            },
            claim_ids=[c.id for c in claims + current],
            source_ids=[s.id, *{c.source_id for c in current}],
            attribute=attribute,
            key=f"stale:{attribute}:{s.id}",
        )

    def notice(self) -> list[Finding]:
        """Announcement vs effective date, against RBI's one-month rule and the bank's own notice
        period. A notice without its own date falls back to the file timestamp and is marked
        uncertain."""
        if not self.pack.notice_rules:  # RBI's notice rule is for card charges only
            return []
        promised = self._promised_notice_days()
        out: list[Finding] = []
        for s in self.sources.values():
            if s.kind != "bank_notice":
                continue
            announced, inferred = s.announced_at, False
            if announced is None and s.published_at is not None:
                announced, inferred = s.published_at, True
            if announced is None:
                continue
            changes = [c for c in self.comparable_claims if c.source_id == s.id]
            by_effective: dict[date, list[ClaimFact]] = defaultdict(list)
            for c in changes:
                eff = self._valid_from(c)
                if eff and eff >= announced:
                    by_effective[eff].append(c)
            if not by_effective and s.effective_from and s.effective_from >= announced:
                by_effective[s.effective_from] = changes
            how = "file date" if inferred else "notice date"
            for eff, cs in sorted(by_effective.items()):
                days = (eff - announced).days
                charge_attrs = sorted({c.attribute for c in cs if self._is_charge(c.attribute)})
                other_attrs = sorted({c.attribute for c in cs} - set(charge_attrs))
                reasons = []
                if charge_attrs and days < RBI_NOTICE_DAYS:
                    reasons.append(
                        f"less than RBI's one-month notice for changes in charges ({days} days)"
                    )
                if promised and days < promised:
                    reasons.append(
                        f"shorter than the bank's own stated notice period ({promised} days)"
                    )
                if not reasons and other_attrs and days < RBI_NOTICE_DAYS:
                    reasons.append(
                        f"{days} days' notice for non-fee changes; RBI's one-month rule clearly "
                        "covers charges, its reach for rewards/lounge is unclear"
                    )
                detail = {
                    "announced_at": announced.isoformat(),
                    "announcement_date_source": "inferred_from_file_timestamp"
                    if inferred
                    else "stated_in_notice",
                    "effective_from": eff.isoformat(),
                    "notice_days": days,
                    "reasons": reasons,
                    "charge_attributes": charge_attrs,
                    "other_attributes": other_attrs,
                    "promised_days": promised,
                    "evidence": [self._evidence(c) for c in cs],
                }
                if not reasons:
                    out.append(
                        Finding(
                            type="notice",
                            subtype="adequate",
                            rule_id="notice.adequate",
                            label="uncertain" if inferred else "sourced",
                            severity=1,
                            confidence=0.6,
                            title=f"Notice check: {how} {announced:%d %b %Y}, effective {eff:%d %b %Y} "
                            f"({days} days) — appears to meet the one-month notice; verify when customers were told",
                            detail=detail,
                            claim_ids=[c.id for c in cs],
                            source_ids=[s.id],
                            key=f"notice:{s.id}:{eff.isoformat()}",
                        )  # fmt: skip
                    )
                    continue
                strong = bool(charge_attrs and days < RBI_NOTICE_DAYS) or bool(
                    promised and days < promised
                )
                label = "sourced" if strong and not inferred else "uncertain"
                out.append(
                    Finding(
                        type="notice",
                        subtype="short",
                        rule_id="notice.short",
                        label=label,  # type: ignore[arg-type]
                        severity=5 if strong else 3,
                        confidence=(0.75 if strong else 0.5) - (0.2 if inferred else 0.0),
                        title=f"May not meet the notice requirement: {how} {announced:%d %b %Y}, "
                        f"effective {eff:%d %b %Y} — verify",
                        detail=detail,
                        claim_ids=[c.id for c in cs],
                        source_ids=[s.id],
                        key=f"notice:{s.id}:{eff.isoformat()}",
                    )  # fmt: skip
                )
        return out

    def _is_charge(self, attribute: str) -> bool:
        spec = self.pack.get(attribute)
        return bool(spec and spec.category in {"fees", "interest"})

    def _promised_notice_days(self) -> int | None:
        values = [
            c.value_norm["value"]
            for c in self.comparable_claims
            if c.attribute == "notice_period"
            and self.sources[c.source_id].kind in TERMS_KINDS
            and c.value_norm
            and c.value_norm.get("type") == "days"
            and c.value_norm.get("value")
        ]
        return int(max(values)) if values else None

    def terms_missing(self) -> list[Finding]:
        """MITC items RBI requires that no MITC/KFS states, checked after the absence search."""
        terms = [s for s in self.sources.values() if s.kind in TERMS_KINDS]
        if not terms:
            return []
        have = {
            c.attribute
            for c in self.comparable_claims
            if self.sources[c.source_id].kind in TERMS_KINDS
        }
        page_count = sum(len(s.pages) for s in terms)
        out: list[Finding] = []
        mentioned: list[Finding] = []
        for spec in self.pack.attributes:
            if not spec.mitc_required or spec.key in have:
                continue
            mentions = find_mentions(spec.keywords, [(s.id, s.pages) for s in terms])
            if mentions:
                mentioned.append(
                    Finding(
                        type="mitc_missing",
                        subtype="mentioned_unextracted",
                        rule_id="mitc_missing.mentioned",
                        label="uncertain",
                        severity=max(1, spec.importance - 2),
                        confidence=0.4,
                        title=f"{spec.label}: mentioned in the terms, but no clear value was found — check page {mentions[0].page_no}",
                        detail={
                            "mentions": [m.__dict__ for m in mentions],
                            "searched_keywords": spec.keywords,
                        },
                        source_ids=sorted({m.source_id for m in mentions}),
                        attribute=spec.key,
                        key=f"mitc_missing:{spec.key}",
                    )
                )
            else:
                out.append(
                    Finding(
                        type="mitc_missing",
                        subtype="absent",
                        rule_id="mitc_missing.absent",
                        label="sourced",
                        severity=spec.importance,
                        confidence=0.7,
                        title=f"{spec.label} not found in {page_count} page(s) of the card's terms (MITC/KFS)",
                        detail={
                            "why": "RBI expects this item in the Most Important Terms and Conditions.",
                            "searched_keywords": spec.keywords,
                            "searched_sources": [s.title for s in terms],
                        },
                        source_ids=[s.id for s in terms],
                        attribute=spec.key,
                        key=f"mitc_missing:{spec.key}",
                    )
                )
        return out + self._group_mentioned(mentioned)

    def _group_mentioned(self, items: list[Finding]) -> list[Finding]:
        # Multi-card terms documents mention many charges without a value for this card; one
        # finding reads better than six near-identical ones.
        if len(items) < 2:
            return items
        pages = sorted({m["page_no"] for f in items for m in f.detail["mentions"][:1]})
        labels = [self._label(f.attribute or "") for f in items]
        return [
            Finding(
                type="mitc_missing",
                subtype="mentioned_group",
                rule_id="mitc_missing.mentioned",
                label="uncertain",
                severity=max(f.severity for f in items),
                confidence=0.4,
                title=(
                    f"{len(items)} terms are mentioned in the card's terms but not clearly stated for "
                    f"this card: {', '.join(labels)}"
                ),
                detail={
                    "items": [
                        {
                            "attribute": f.attribute,
                            "label": lbl,
                            "page_no": f.detail["mentions"][0]["page_no"],
                        }
                        for f, lbl in zip(items, labels, strict=True)
                    ],
                    "pages": pages,
                    "mentions": [f.detail["mentions"][0] for f in items],
                },
                source_ids=sorted({s for f in items for s in f.source_ids}),
                key="mitc_missing:mentioned",
            )
        ]

    def unanswered(self) -> list[Finding]:
        """Sub-questions (from the AI planner) that no verified claim answers."""
        have = {c.attribute for c in self.comparable_claims}
        everything = [(s.id, s.pages) for s in self.sources.values() if not s.redirected_to]
        out: list[Finding] = []
        for i, q in enumerate(self.sub_questions):
            attrs = [a for a in q.attributes if self.pack.get(a)]
            if attrs and any(a in have for a in attrs):
                continue
            keywords = [k for a in attrs for k in self.pack.get(a).keywords]  # type: ignore[union-attr]
            mentions = find_mentions(keywords, everything) if keywords else []
            out.append(
                Finding(
                    type="unanswered",
                    rule_id="gap.question",
                    label="ai_suggestion" if not mentions else "uncertain",
                    severity=max([self._importance(a) for a in attrs], default=3)
                    - (1 if mentions else 0),
                    confidence=0.6 if not mentions else 0.4,
                    title=(
                        f"Potential gap: “{q.text}” is not answered by the {len(self.sources)} sources reviewed"
                        if not mentions
                        else f"Possibly answered but unclear: “{q.text}” — the topic is mentioned, check page {mentions[0].page_no}"
                    ),
                    detail={
                        "question": q.text,
                        "attributes": attrs,
                        "searched_keywords": keywords,
                        "mentions": [m.__dict__ for m in mentions],
                        "why": "Sub-question proposed by the AI planner; the answer check is done by code.",
                    },
                    source_ids=sorted({m.source_id for m in mentions}),
                    key=f"unanswered:{i}",
                )
            )
        return out

    def chat_mismatch(self) -> list[Finding]:
        """What customer care said vs the issuer terms valid on that date."""
        out: list[Finding] = []
        official = [c for c in self.comparable_claims if self.sources[c.source_id].is_issuer]
        for c in self.all_claims:
            s = self.sources.get(c.source_id)
            if (
                s is None
                or s.kind != "user_chat"
                or not c.value_norm
                or not c.value_norm.get("parsed")
            ):
                continue
            said = s.said_at or self.today
            candidates = [
                o for o in official
                if o.attribute == c.attribute and (self._valid_from(o) is None or self._valid_from(o) <= said)  # type: ignore[operator]
            ]  # fmt: skip
            if not candidates:
                continue
            latest = max((self._valid_from(o) or date.min) for o in candidates)
            valid_then = [o for o in candidates if (self._valid_from(o) or date.min) == latest]
            if self._sets_match([c], valid_then):
                continue
            if not any(comparable(c.value_norm, o.value_norm) for o in valid_then):
                continue
            out.append(
                Finding(
                    type="chat_mismatch",
                    rule_id="chat.mismatch",
                    label="sourced",
                    severity=max(3, self._importance(c.attribute)),
                    confidence=0.75,
                    title=f"What you were told may not match the terms: {self._label(c.attribute)} "
                    f"on {said:%d %b %Y}",
                    detail={
                        "said_at": said.isoformat(),
                        "told": self._evidence(c),
                        "terms_valid_then": [self._evidence(o) for o in valid_then],
                    },
                    claim_ids=[c.id, *[o.id for o in valid_then]],
                    source_ids=[s.id, *{o.source_id for o in valid_then}],
                    attribute=c.attribute,
                    key=f"chat:{c.id}",
                )
            )
        return out
