"""notice_reads (공지 읽음 상태)

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notice_reads',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('notice_id', sa.String(length=36), nullable=False),
        sa.Column('employee_id', sa.String(length=36), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['notice_id'], ['notices.id']),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('notice_id', 'employee_id', name='uq_notice_read'),
    )
    op.create_index('ix_notice_reads_notice_id', 'notice_reads', ['notice_id'])
    op.create_index('ix_notice_reads_employee_id', 'notice_reads', ['employee_id'])


def downgrade() -> None:
    op.drop_index('ix_notice_reads_employee_id', table_name='notice_reads')
    op.drop_index('ix_notice_reads_notice_id', table_name='notice_reads')
    op.drop_table('notice_reads')
