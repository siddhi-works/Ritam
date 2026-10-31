"""Near-duplicate text between sources (MinHash over word 5-shingles)."""

import re
from dataclasses import dataclass

from datasketch import MinHash

from app.analysis.facts import ClaimFact, Finding, SourceFact

_WORD = re.compile(r"\w+")
NUM_PERM = 128
COPY_THRESHOLD = 0.5


@dataclass(frozen=True)
class CopyEdge:
    copier: str
    original: str
    similarity: float
    lag_days: int | None


def _minhash(text: str, k: int = 5) -> MinHash | None:
    words = _WORD.findall(text.lower())
    if len(words) < k * 4:
        return None
    m = MinHash(num_perm=NUM_PERM, seed=7)
    for i in range(len(words) - k + 1):
        m.update(" ".join(words[i : i + k]).encode("utf-8"))
    return m


def _older_or_more_authoritative(a: SourceFact, b: SourceFact) -> bool:
    """True if `a` is the more likely original."""
    if a.tier != b.tier:
        return a.tier < b.tier
    da, db = a.best_date or a.observed_at, b.best_date or b.observed_at
    if da and db and da != db:
        return da < db
    return a.id < b.id


def copy_edges(sources: list[SourceFact], threshold: float = COPY_THRESHOLD) -> list[CopyEdge]:
    """Only third-party sources can be copiers. Two issuer documents sharing text are versions of
    the same document."""
    hashes = {s.id: _minhash("\n".join(s.pages)) for s in sources}
    by_id = {s.id: s for s in sources}
    edges: list[CopyEdge] = []
    ids = sorted(k for k, v in hashes.items() if v is not None)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            sim = hashes[a].jaccard(hashes[b])  # type: ignore[union-attr]
            if sim < threshold:
                continue
            sa, sb = by_id[a], by_id[b]
            if sa.is_issuer and sb.is_issuer:
                continue
            original, copier = (sa, sb) if _older_or_more_authoritative(sa, sb) else (sb, sa)
            od, cd = (
                original.best_date or original.observed_at,
                copier.best_date or copier.observed_at,
            )
            lag = (cd - od).days if od and cd else None
            edges.append(CopyEdge(copier.id, original.id, round(sim, 3), lag))
    return edges


def _root(source_id: str, parent: dict[str, str]) -> str:
    seen = set()
    while source_id in parent and source_id not in seen:
        seen.add(source_id)
        source_id = parent[source_id]
    return source_id


def single_origin_findings(
    sources: list[SourceFact], claims: list[ClaimFact], edges: list[CopyEdge]
) -> list[Finding]:
    if not edges:
        return []
    parent = {e.copier: e.original for e in sorted(edges, key=lambda e: -e.similarity)}
    by_attr: dict[str, set[str]] = {}
    for c in claims:
        by_attr.setdefault(c.attribute, set()).add(c.source_id)
    names = {s.id: s.title for s in sources}
    out: list[Finding] = []
    for attribute, supporters in by_attr.items():
        if len(supporters) < 2:
            continue
        roots = {_root(s, parent) for s in supporters}
        if len(roots) != 1:
            continue
        root = roots.pop()
        out.append(
            Finding(
                type="single_origin",
                rule_id="single_origin",
                label="uncertain",
                severity=2,
                confidence=0.6,
                title=f"{len(supporters)} sources agree on this, but their text appears copied from one original",
                detail={
                    "attribute": attribute,
                    "original": names.get(root, root),
                    "supporters": sorted(names.get(s, s) for s in supporters),
                    "edges": [
                        e.__dict__
                        for e in edges
                        if e.copier in supporters or e.original in supporters
                    ],
                },
                claim_ids=[c.id for c in claims if c.attribute == attribute],
                source_ids=sorted(supporters),
                attribute=attribute,
                key=f"single_origin:{attribute}",
            )
        )
    return out
