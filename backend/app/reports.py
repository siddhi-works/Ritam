"""Which reports are public. A report that includes a person's own chat or upload stays private to
its link; sample reports are public by design. Every query that shares reports across people goes
through here, so the rule exists once."""

from typing import Any

from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Audit, AuditSource, AuditStatus, Source, SourceKind

USER_KINDS = (SourceKind.USER_CHAT, SourceKind.USER_UPLOAD)


def public_report(*products: str) -> list[ColumnElement[Any]]:
    """WHERE clauses: a finished report on one of `products` built only from public sources."""
    personal = exists().where(
        AuditSource.audit_id == Audit.id,
        AuditSource.source_id == Source.id,
        Source.kind.in_(USER_KINDS),
    )
    return [
        Audit.product_name.in_(products),
        Audit.status.in_([AuditStatus.COMPLETE, AuditStatus.PARTIAL]),
        or_(Audit.is_demo.is_(True), ~personal),
    ]


async def latest_public_reports(session: AsyncSession, products: list[str]) -> dict[str, Audit]:
    """The newest public report for each product, in one query."""
    rows = await session.scalars(
        select(Audit)
        .where(*public_report(*products))
        .order_by(Audit.product_name, Audit.finished_at.desc().nulls_last())
        .distinct(Audit.product_name)
    )
    return {a.product_name: a for a in rows if a.product_name}


async def latest_public_report(session: AsyncSession, product: str) -> Audit | None:
    return (await latest_public_reports(session, [product])).get(product)
