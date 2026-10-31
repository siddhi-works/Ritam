"""audit pack

Revision ID: 5c2e9a41d7b3
Revises: 033c3cedb50a
Create Date: 2026-11-01 04:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c2e9a41d7b3'
down_revision: Union[str, Sequence[str], None] = '033c3cedb50a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'audit',
        sa.Column('pack', sa.String(length=40), server_default='credit_card', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('audit', 'pack')
