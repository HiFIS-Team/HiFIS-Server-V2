"""payslips.incentive_*_auto — 서버가 계산한 원래 커미션

신청할 때 본인이 PT 커미션을 고칠 수 있게 되면서, 고친 값으로 덮어써 버리면
**결재하는 쪽이 무엇을 승인하는지 모른다.** 원래 계산값을 따로 남긴다.

기존 명세서는 고쳐진 적이 없으므로 지금 값 그대로 백필한다.

Revision ID: 9c0d1e2f3a4b
Revises: 8b9c0d1e2f3a
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9c0d1e2f3a4b"
down_revision: Union[str, Sequence[str], None] = "8b9c0d1e2f3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payslips", sa.Column("incentive_new_auto", sa.Integer(), nullable=True))
    op.add_column("payslips", sa.Column("incentive_renewal_auto", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE payslips SET incentive_new_auto = incentive_new, "
        "incentive_renewal_auto = incentive_renewal"
    )


def downgrade() -> None:
    op.drop_column("payslips", "incentive_renewal_auto")
    op.drop_column("payslips", "incentive_new_auto")
