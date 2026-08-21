"""개인 업무 확정 누락 (my_task_misses)

다음 근무일까지도 안 한 하루를 한 줄로 남긴다. 당사자 -20점과 점장 기본급
차감이 둘 다 이 표를 센다 (2026-08-21 대표 결정).

Revision ID: tms000000001
Revises: pts000000001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "tms000000001"
down_revision = "pts000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "my_task_misses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("employee_id", sa.String(length=36), nullable=False),
        sa.Column("branch_id", sa.String(length=36), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("task_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contents", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("score_event_id", sa.String(length=36), nullable=True),
        sa.Column("excuse_reason", sa.Text(), nullable=True),
        sa.Column("excuse_status", sa.String(length=20), nullable=True),
        sa.Column("decided_by_id", sa.String(length=36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["decided_by_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
        # 하루에 한 줄 — 업무를 몇 개 빠뜨렸든, 잡이 며칠 더 집든 하나다
        sa.UniqueConstraint("employee_id", "date", name="uq_my_task_miss_day"),
    )
    op.create_index("ix_my_task_misses_employee_id", "my_task_misses", ["employee_id"])
    op.create_index("ix_my_task_misses_branch_id", "my_task_misses", ["branch_id"])
    op.create_index("ix_my_task_misses_date", "my_task_misses", ["date"])


def downgrade() -> None:
    op.drop_index("ix_my_task_misses_date", table_name="my_task_misses")
    op.drop_index("ix_my_task_misses_branch_id", table_name="my_task_misses")
    op.drop_index("ix_my_task_misses_employee_id", table_name="my_task_misses")
    op.drop_table("my_task_misses")
