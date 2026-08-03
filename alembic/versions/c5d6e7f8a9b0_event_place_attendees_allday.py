"""events.place / attendee_ids / all_day

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-08-03 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, Sequence[str], None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('all_day', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('events', sa.Column('place', sa.String(length=200), nullable=True))
    op.add_column(
        'events',
        sa.Column('attendee_ids', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('events', 'attendee_ids')
    op.drop_column('events', 'place')
    op.drop_column('events', 'all_day')
