"""employee.shift_start / shift_end (기본 근무 시간, 근무외출근 자동 판정용)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('shift_start', sa.String(length=5), nullable=True))
    op.add_column('employees', sa.Column('shift_end', sa.String(length=5), nullable=True))


def downgrade() -> None:
    op.drop_column('employees', 'shift_end')
    op.drop_column('employees', 'shift_start')
