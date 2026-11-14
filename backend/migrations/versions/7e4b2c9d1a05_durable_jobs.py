"""durable jobs

Revision ID: 7e4b2c9d1a05
Revises: 5c2e9a41d7b3
Create Date: 2026-11-14 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7e4b2c9d1a05"
down_revision: str | Sequence[str] | None = "5c2e9a41d7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS = postgresql.ENUM("queued", "running", "done", "failed", name="job_status", create_type=False)


def upgrade() -> None:
    STATUS.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", STATUS, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("starts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_claim", "job", ["status", "run_after"])
    op.create_index(
        "ix_job_live_subject",
        "job",
        [sa.text("(args ->> 0)")],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("ix_job_live_subject", table_name="job")
    op.drop_index("ix_job_claim", table_name="job")
    op.drop_table("job")
    STATUS.drop(op.get_bind(), checkfirst=True)
