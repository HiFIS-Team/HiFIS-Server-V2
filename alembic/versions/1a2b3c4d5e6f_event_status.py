"""events.status — 승인 대기(PENDING) / 승인됨(APPROVED)

Revision ID: 1a2b3c4d5e6f
Revises: f0a1b2c3d4e5
Create Date: 2026-08-04 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    status = sa.Enum('PENDING', 'APPROVED', name='eventstatus')
    status.create(op.get_bind(), checkfirst=True)
    # 이미 달력에 떠 있던 일정은 전부 승인된 것으로 둔다 —
    # 규칙이 생기기 전에 올린 것을 소급해 감추면 달력이 갑자기 빈다
    op.add_column(
        'events',
        sa.Column('status', status, nullable=False, server_default='APPROVED'),
    )
    op.create_index('ix_events_status', 'events', ['status'])
    op.alter_column('events', 'status', server_default=None)


def downgrade() -> None:
    op.drop_index('ix_events_status', table_name='events')
    op.drop_column('events', 'status')
    sa.Enum(name='eventstatus').drop(op.get_bind(), checkfirst=True)
