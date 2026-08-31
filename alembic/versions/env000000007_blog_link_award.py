"""스토리 3 → 2 · 블로그 10 → 3 · 블로그 링크와 대표 가산점

대표 결정 (2026-08-28).

- **배점을 내린다.** 스토리 3 → 2, 블로그 10 → 3. 블로그는 현수막·클레임해결과
  같은 10점 자리에 있었는데, 글 하나로 10점이면 다른 항목을 안 하게 된다.
- **대신 대표가 얹는다.** 잘 쓴 글에는 [`POST /env-logs/{id}/award`] 로
  가산점을 준다 (프로젝트 점수 부여와 같은 방식). 기본 3 + 가산점이 최종이다.
- **링크를 같이 받는다.** 안 받으면 대표가 무엇을 보고 매길지가 없다.
  현수막이 사진을 받는 것과 같은 자리다.

**이미 쌓인 수행 기록(`env_task_logs`)은 안 건드린다.** 거기 `points` 는 누른
순간의 값을 복사해 둔 것이라, 지금 바꾸면 지난달 점수가 소급해서 바뀐다.
점수 원장(`score_events`)도 같은 이유로 그대로 둔다 (`env000000006` 과 같은 규칙).

Revision ID: env000000007
Revises: env000000006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "env000000007"
down_revision: Union[str, Sequence[str], None] = "env000000006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 지점마다 한 벌씩 있어서 이름으로 한 번에 내린다
    op.execute("UPDATE env_items SET points = 2 WHERE name = '스토리'")
    op.execute("UPDATE env_items SET points = 3 WHERE name = '블로그'")

    op.add_column("env_task_logs", sa.Column("link", sa.String(500), nullable=True))
    # 가산점 — 기본 배점 위에 얹는 값이다 (기본 3 + 가산 7 = 10)
    op.add_column(
        "env_task_logs",
        sa.Column("bonus_points", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("env_task_logs", sa.Column("bonus_reason", sa.Text(), nullable=True))
    op.add_column("env_task_logs", sa.Column("bonus_by_id", sa.String(36), nullable=True))
    op.add_column(
        "env_task_logs", sa.Column("bonus_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "env_task_logs_bonus_by_id_fkey",
        "env_task_logs",
        "employees",
        ["bonus_by_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("env_task_logs_bonus_by_id_fkey", "env_task_logs", type_="foreignkey")
    op.drop_column("env_task_logs", "bonus_at")
    op.drop_column("env_task_logs", "bonus_by_id")
    op.drop_column("env_task_logs", "bonus_reason")
    op.drop_column("env_task_logs", "bonus_points")
    op.drop_column("env_task_logs", "link")

    op.execute("UPDATE env_items SET points = 3 WHERE name = '스토리'")
    op.execute("UPDATE env_items SET points = 10 WHERE name = '블로그'")
