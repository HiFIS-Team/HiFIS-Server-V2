"""이달의 목표 — 줄마다 이뤘는지

Revision ID: gol000000002
Revises: gol000000001
Create Date: 2026-09-28

본인이 목표 줄마다 달성을 체크한다 (`achieved`, 이룬 줄 번호 목록).
달성률과 월별 그래프의 재료다.
"""

import sqlalchemy as sa
from alembic import op

revision = "gol000000002"
down_revision = "gol000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monthly_goals",
        sa.Column("achieved", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("monthly_goals", "achieved")
