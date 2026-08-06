"""employees.resigned_at (퇴사 시각 §58)

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-08-03 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9b0c1d2e3f4'
down_revision: Union[str, Sequence[str], None] = 'f8a9b0c1d2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('resigned_at', sa.DateTime(timezone=True), nullable=True))
    # 기존 퇴사자(RESIGNED) 백필 — 삭제 시각(deleted_at)을 퇴사 시각으로 추정
    op.execute(
        "UPDATE employees SET resigned_at = deleted_at "
        "WHERE status = 'RESIGNED' AND resigned_at IS NULL AND deleted_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column('employees', 'resigned_at')
