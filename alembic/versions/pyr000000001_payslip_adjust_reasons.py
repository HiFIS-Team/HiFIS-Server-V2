"""급여 신청 — 커미션을 고친 이유

Revision ID: pyr000000001
Revises: bdc000000001
Create Date: 2026-09-27

신청서에서 PT 커미션을 서버 계산값과 다르게 내면 **이유가 필수다.**
결재하는 쪽이 왜 바꿨는지 봐야 승인할 수 있다. 특이사항(`note`)과 따로 둔다 —
그 칸은 선택이고, 한 칸에 섞으면 어느 금액의 이유인지 갈리지 않는다.
"""

import sqlalchemy as sa
from alembic import op

revision = "pyr000000001"
down_revision = "bdc000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payslips", sa.Column("incentive_new_reason", sa.Text(), nullable=True))
    op.add_column("payslips", sa.Column("incentive_renewal_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("payslips", "incentive_renewal_reason")
    op.drop_column("payslips", "incentive_new_reason")
