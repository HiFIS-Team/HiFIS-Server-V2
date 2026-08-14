"""내 업무 — my_tasks · my_task_checks · my_task_requests

업무 화면 '환경정비' 자리가 **공통 업무 / 내 업무** 둘로 갈렸다 (2026-08-14).

| | 하루에 |
|---|---|
| 공통 업무 (`env_items`) | **여러 번** — 할 때마다 횟수가 는다 |
| 내 업무 (`my_tasks`) | **한 번씩 체크** — 다 하면 완료, 남으면 누락 |

- **점수 칸이 없다.** 그날 할 일을 챙기는 용도라 배점을 안 붙이기로 했다
- **목록은 매일 반복된다.** 체크만 날짜별로 따로 쌓인다 (`my_task_checks`)
- **추가는 본인이, 수정·삭제는 MASTER 결재** (`my_task_requests`) —
  프로젝트 수정·삭제와 같은 이유다

`my_tasks.deleted_at` 은 소프트 삭제다. 행을 지우면 CASCADE 로 체크 기록까지
사라져서, 지난 날짜를 다시 보면 하지도 않은 일을 한 것처럼 보인다.

Revision ID: mtk000000001
Revises: env000000003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "mtk000000001"
down_revision: Union[str, Sequence[str], None] = "env000000003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "my_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("content", sa.String(200), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_my_tasks_employee_id", "my_tasks", ["employee_id"])

    op.create_table(
        "my_task_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "my_task_id",
            sa.String(36),
            sa.ForeignKey("my_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # 같은 날 같은 업무를 두 번 체크할 수 없다 — 공통 업무와 다른 점이다
        sa.UniqueConstraint("my_task_id", "date", name="uq_my_task_check_day"),
    )
    op.create_index("ix_my_task_checks_my_task_id", "my_task_checks", ["my_task_id"])
    op.create_index("ix_my_task_checks_employee_id", "my_task_checks", ["employee_id"])
    op.create_index("ix_my_task_checks_date", "my_task_checks", ["date"])

    op.create_table(
        "my_task_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "my_task_id",
            sa.String(36),
            sa.ForeignKey("my_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "requested_by_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False
        ),
        sa.Column("decided_by_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_my_task_requests_my_task_id", "my_task_requests", ["my_task_id"])
    op.create_index(
        "ix_my_task_requests_requested_by_id", "my_task_requests", ["requested_by_id"]
    )


def downgrade() -> None:
    op.drop_table("my_task_requests")
    op.drop_table("my_task_checks")
    op.drop_table("my_tasks")
