"""Build the preloaded demo audits.

    python -m app.seed --demo-dir ../demo-docs [--only axis]

Files are checked against demo-docs/manifest.json (SHA-256) before ingest.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.pipeline import run_audit
from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.ingest.fetch import Fetcher, FetchResult, make_fetcher
from app.ingest.service import IngestInput, ingest
from app.llm import make_router
from app.llm.budget import SqlBudget
from app.models import Audit, AuditSource, AuditStatus, Source, SourceKind
from app.observability import configure_logging
from app.packs import load_pack
from app.storage import LocalStore

log = logging.getLogger(__name__)

SAMPLE_CHAT_HDFC = (
    "SAMPLE (illustrative, not a real customer conversation; written for the Ritam demo)\n"
    "Date of chat: 20 Oct 2026\n"
    "Customer: Is there any annual fee on the Millennia card?\n"
    "Agent: The renewal fee is Rs. 1,000 plus taxes, but it is waived if you spend Rs 50,000 in a year.\n"
    "Customer: And cashback on wallet reloads?\n"
    "Agent: Yes, you get 1% cashback on wallet reloads too."
)


@dataclass
class FileSource:
    file: str
    kind: SourceKind
    title: str | None = None


@dataclass
class UrlSource:
    url: str
    kind: SourceKind
    title: str | None = None


@dataclass
class TextSource:
    text: str
    kind: SourceKind
    title: str
    said_at: date | None = None


@dataclass
class DemoCase:
    slug: str
    question: str
    product: str
    sources: list[FileSource | UrlSource | TextSource] = field(default_factory=list)
    pack: str = "credit_card"


CASES = [
    DemoCase(
        slug="axis",
        question=(
            "Did Axis Bank change the Magnus card's charges and benefits from 28 August 2026, "
            "and were customers given proper notice?"
        ),
        product="Axis Bank Magnus credit card",
        sources=[
            FileSource(
                "axis_mitc_old_wayback_2025-08-09.pdf",
                SourceKind.MITC_PDF,
                "Axis Bank credit card MITC (archived 9 Aug 2025)",
            ),
            FileSource(
                "axis_mitc_new.pdf", SourceKind.MITC_PDF, "Axis Bank credit card MITC (current)"
            ),
            FileSource(
                "axis_magnus_revision_notice.pdf",
                SourceKind.BANK_NOTICE,
                "Axis Bank notice: revision of Magnus card terms",
            ),
            FileSource(
                "aggregator_paisabazaar_magnus.html",
                SourceKind.AGGREGATOR,
                "Paisabazaar: Axis Magnus card page",
            ),
            UrlSource(
                "https://www.businesstoday.in/personal-finance/story/axis-bank-credit-card-rules-dcc-markup-to-rise-to-3-5-late-fee-goes-up-to-rs1300-549766-2026-08-18",
                SourceKind.NEWS,
            ),
        ],
    ),
    DemoCase(
        slug="hdfc",
        question=(
            "Is the HDFC Millennia card's information consistent and current across HDFC and "
            "comparison sites? What should I verify before applying?"
        ),
        product="HDFC Bank Millennia credit card",
        sources=[
            FileSource(
                "hdfc_millennia_terms.pdf",
                SourceKind.OFFICIAL_PAGE,
                "HDFC Bank Millennia card: features and fees (2025)",
            ),
            FileSource(
                "hdfc_millennia_fees_2022.pdf",
                SourceKind.OFFICIAL_PAGE,
                "HDFC Bank Millennia card brochure (older, undated)",
            ),
            UrlSource(
                "https://www.hdfcbank.com/personal/pay/cards/credit-cards/millennia-credit-card",
                SourceKind.OFFICIAL_PAGE,
                "HDFC Millennia (old hdfcbank.com link)",
            ),
            UrlSource(
                "https://www.hdfc.bank.in/credit-cards/millennia-credit-card",
                SourceKind.OFFICIAL_PAGE,
            ),
            FileSource(
                "aggregator_paisabazaar_millennia.html",
                SourceKind.AGGREGATOR,
                "Paisabazaar: HDFC Millennia card page",
            ),
            FileSource(
                "aggregator_bankbazaar_millennia.html",
                SourceKind.AGGREGATOR,
                "BankBazaar: HDFC Millennia card page",
            ),
            TextSource(
                SAMPLE_CHAT_HDFC,
                SourceKind.USER_CHAT,
                "SAMPLE customer-care chat (illustrative)",
                date(2026, 10, 20),
            ),
        ],
    ),
    DemoCase(
        slug="icici",
        question=(
            "Does the ICICI Amazon Pay card's MITC cover everything RBI expects, and what is "
            "unclear or missing?"
        ),
        product="ICICI Bank Amazon Pay credit card",
        sources=[
            FileSource(
                "icici_amazon_pay_mitc.pdf", SourceKind.MITC_PDF, "ICICI Bank Amazon Pay card MITC"
            ),
            FileSource(
                "icici_mitc.pdf", SourceKind.MITC_PDF, "ICICI Bank credit card MITC (all cards)"
            ),
        ],
    ),
]


def _manifest(demo_dir: Path) -> dict[str, dict[str, object]]:
    rows = json.loads((demo_dir / "manifest.json").read_text(encoding="utf-8"))
    return {str(r["file"]): r for r in rows}


async def _source_for(
    item: FileSource | UrlSource | TextSource,
    *,
    session: AsyncSession,
    store: LocalStore,
    settings: Settings,
    fetcher: Fetcher,
    manifest: dict[str, dict[str, object]],
    demo_dir: Path,
) -> Source:
    if isinstance(item, FileSource):
        meta = manifest.get(item.file)
        if meta is None:
            raise SystemExit(f"{item.file} is not in manifest.json")
        body = (demo_dir / item.file).read_bytes()
        if hashlib.sha256(body).hexdigest() != meta["sha256"]:
            raise SystemExit(f"{item.file}: SHA-256 does not match manifest.json; refusing to seed")
        archived = meta.get("archived_at")
        fetched = FetchResult(
            requested_url=str(meta["url"]),
            final_url=str(meta.get("final_url") or meta["url"]),
            status=200,
            content_type=str(meta.get("content_type", "")),
            body=body,
            method="snapshot",
            fetched_at=datetime.fromisoformat(str(meta["downloaded"])).replace(tzinfo=UTC),
            archived_at=datetime.fromisoformat(str(archived).replace("Z", "+00:00"))
            if archived
            else None,
            attempts=[{"method": "snapshot", "file": item.file, "sha256": meta["sha256"]}],
        )
        src, _ = await ingest(session, store, settings, IngestInput(
            body=body, kind=item.kind, title=item.title, url=str(meta["url"]), filename=item.file,
            content_type=fetched.content_type, fetch=fetched,
        ))  # fmt: skip
        if item.title:
            src.title = item.title  # also when an identical file was ingested before
        return src
    if isinstance(item, TextSource):
        src, _ = await ingest(session, store, settings, IngestInput(
            body=item.text.encode("utf-8"), kind=item.kind, title=item.title,
            content_type="text/plain", said_at=item.said_at,
        ))  # fmt: skip
        return src
    fetched = await fetcher.fetch(item.url)
    src, _ = await ingest(session, store, settings, IngestInput(
        body=fetched.body, kind=item.kind, title=item.title, url=item.url,
        content_type=fetched.content_type, fetch=fetched,
    ))  # fmt: skip
    return src


async def seed(demo_dir: Path, only: str | None) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    llm = make_router(settings)
    llm.budget = SqlBudget(
        sessionmaker, settings.llm_daily_budget
    )  # seeding counts towards today's quota
    fetcher = make_fetcher(settings.js_fallback)
    store = LocalStore(settings.raw_store_dir)
    manifest = _manifest(demo_dir)
    try:
        for case in CASES:
            if only and case.slug != only:
                continue
            async with sessionmaker() as session:
                audit = Audit(id=uuid.uuid4(), question=case.question, product_name=case.product,
                              pack=case.pack, status=AuditStatus.QUEUED, stats={}, is_demo=False)  # fmt: skip
                session.add(audit)
                ids: list[uuid.UUID] = []
                for item in case.sources:
                    try:
                        src = await _source_for(item, session=session, store=store, settings=settings,
                                                fetcher=fetcher, manifest=manifest, demo_dir=demo_dir)  # fmt: skip
                    except SystemExit:
                        raise
                    except Exception as exc:  # noqa: BLE001 - a live URL may fail; the demo continues
                        print(
                            f"  [{case.slug}] skipped {item}: {type(exc).__name__}: {str(exc)[:120]}"
                        )
                        continue
                    if src.id not in ids:
                        ids.append(src.id)
                await session.flush()
                session.add_all(AuditSource(audit_id=audit.id, source_id=sid) for sid in ids)
                await session.commit()
                print(f"[{case.slug}] audit {audit.id} with {len(ids)} sources; running pipeline…")
                done = await run_audit(session, audit_id=audit.id, llm=llm, fetcher=fetcher,
                                       store=store, settings=settings, pack=load_pack(case.pack))  # fmt: skip
                print(f"[{case.slug}] {done.status.value}: {done.stats.get('findings')} findings, "
                      f"{done.stats.get('claims_verified')} verified claims")  # fmt: skip
                if done.status == AuditStatus.FAILED:
                    print(f"[{case.slug}] kept the previous example")
                    continue
                # Swap only after the new example finished, so a failed rebuild never loses one.
                old = list(await session.scalars(
                    select(Audit.id).where(Audit.is_demo.is_(True), Audit.product_name == case.product)
                ))  # fmt: skip
                await session.execute(delete(Audit).where(Audit.id.in_(old)))
                done.is_demo = True
                await session.commit()
    finally:
        await llm.aclose()
        await fetcher.aclose()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--demo-dir", type=Path, default=Path("../demo-docs"))
    parser.add_argument("--only", choices=[c.slug for c in CASES])
    args = parser.parse_args()
    asyncio.run(seed(args.demo_dir, args.only))


if __name__ == "__main__":
    main()
