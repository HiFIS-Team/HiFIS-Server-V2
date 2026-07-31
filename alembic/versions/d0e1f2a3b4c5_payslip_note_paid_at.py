"""payslip.note + paid_at (신청 특이사항 · 지급 완료)

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-31 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('payslips', sa.Column('note', sa.Text(), nullable=True))
    op.add_column('payslips', sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True))
    # PayslipStatus.PAID 는 native_enum=False(VARCHAR) → 컬럼 변경 불필요


def downgrade() -> None:
    op.drop_column('payslips', 'paid_at')
    op.drop_column('payslips', 'note')
