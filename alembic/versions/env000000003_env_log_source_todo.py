"""env_task_logs.source_todo_id — 프로젝트 할 일에서 나온 환경정비 기록

`현수막 설치 1` 처럼 할 일에 환경정비 항목 이름이 들어 있으면, 체크하는 순간
환경정비 수행 기록과 점수가 같이 생긴다 (2026-08-14 결정).

**체크를 풀면 그것만 정확히 걷어야 한다.** 안 그러면 체크·해제를 반복해
점수를 무한히 쌓을 수 있다. 어느 할 일에서 나온 기록인지 여기 남긴다.

칩을 눌러 직접 남긴 기록은 null 이다 — 이미 쌓인 행이 다 그렇다.

`ondelete="SET NULL"` 인 이유: 할 일을 지워도 **이미 한 일의 기록과 점수는
남아야 한다.** CASCADE 로 두면 할 일을 지우는 순간 점수 근거가 사라진다.

Revision ID: env000000003
Revises: prq000000001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "env000000003"
down_revision: Union[str, Sequence[str], None] = "prq000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("env_task_logs", sa.Column("source_todo_id", sa.String(36), nullable=True))
    op.create_index("ix_env_task_logs_source_todo_id", "env_task_logs", ["source_todo_id"])
    op.create_foreign_key(
        "fk_env_task_logs_source_todo_id",
        "env_task_logs",
        "project_todos",
        ["source_todo_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_env_task_logs_source_todo_id", "env_task_logs", type_="foreignkey")
    op.drop_index("ix_env_task_logs_source_todo_id", table_name="env_task_logs")
    op.drop_column("env_task_logs", "source_todo_id")
