"""생일 · 개인 업무 월 단위 차례

Revision ID: bdm000000001
Revises: ptt000000001
Create Date: 2026-09-21

두 칸 다 **null 이 뜻을 가진다** — 기존 행을 채우지 않는다.

| 칸 | null 일 때 |
|---|---|
| `employees.birthday` | 아직 안 받았다 → 첫 로그인에 한 번 묻는다 |
| `my_tasks.monthdays` | 요일로 도는 업무다 → `weekdays` 가 정한다 |

`monthdays` 를 `weekdays` 옆에 **더한다.** 요일 칸을 날짜로 바꿔 쓰면
1~7 이 월요일인지 1일인지를 값만 보고는 못 가른다 — 이미 쌓인 업무가
전부 `{1..7}`(매일) 이라 그대로 날짜로 읽히면 매달 1~7일만 서게 된다.
"""

import sqlalchemy as sa
from alembic import op

revision = "bdm000000001"
down_revision = "ptt000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("birthday", sa.Date(), nullable=True))
    op.add_column(
        "my_tasks",
        sa.Column("monthdays", sa.ARRAY(sa.Integer()), nullable=True),
    )
    # 개인 업무 체크에서 저절로 생긴 환경정비 기록이면 그 체크를 가리킨다.
    # **되짚기용이다** — 할 일 쪽(`source_todo_id`)이 끈이 끊겨서 점수가 새는
    # 것을 한동안 못 봤다. 같은 자리를 또 만들지 않는다.
    op.add_column(
        "env_task_logs",
        sa.Column("source_my_task_check_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_env_task_logs_source_my_task_check_id",
        "env_task_logs",
        ["source_my_task_check_id"],
    )
    op.create_foreign_key(
        "fk_env_task_logs_my_task_check",
        "env_task_logs",
        "my_task_checks",
        ["source_my_task_check_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_env_task_logs_my_task_check", "env_task_logs", type_="foreignkey")
    op.drop_index("ix_env_task_logs_source_my_task_check_id", table_name="env_task_logs")
    op.drop_column("env_task_logs", "source_my_task_check_id")
    op.drop_column("my_tasks", "monthdays")
    op.drop_column("employees", "birthday")
