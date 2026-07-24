"""ranking_snapshots table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-24 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ranking_snapshots',
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('employee_id', sa.String(length=36), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kind', 'period', 'employee_id', name='uq_ranking_snapshot'),
    )
    op.create_index(op.f('ix_ranking_snapshots_kind'), 'ranking_snapshots', ['kind'])
    op.create_index(op.f('ix_ranking_snapshots_period'), 'ranking_snapshots', ['period'])


def downgrade() -> None:
    op.drop_index(op.f('ix_ranking_snapshots_period'), table_name='ranking_snapshots')
    op.drop_index(op.f('ix_ranking_snapshots_kind'), table_name='ranking_snapshots')
    op.drop_table('ranking_snapshots')
