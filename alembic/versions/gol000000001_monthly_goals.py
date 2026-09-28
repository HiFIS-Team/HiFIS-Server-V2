"""이달의 목표

Revision ID: gol000000001
Revises: ptr000000001
Create Date: 2026-09-28

MANAGER·MEMBER 가 달마다 스스로 적는 목표 (최소 2개). 사람·달당 한 줄이고
한 번 내면 잠긴다 (`app/models/staff/monthly_goal.py`).
"""

import sqlalchemy as sa
from alembic import op

revision = "gol000000001"
down_revision = "ptr000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monthly_goals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("year_month", sa.String(7), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("employee_id", "year_month", name="uq_monthly_goal"),
    )
    op.create_index("ix_monthly_goals_employee_id", "monthly_goals", ["employee_id"])
    op.create_index("ix_monthly_goals_year_month", "monthly_goals", ["year_month"])


def downgrade() -> None:
    op.drop_table("monthly_goals")
