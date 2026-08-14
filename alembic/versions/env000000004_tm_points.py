"""TM회원관리 배점 1 → 5

대표 결정 (2026-08-14). 전화로 회원을 붙잡는 일이 세탁·건조기와 같은 1점이라
실제 품에 비해 낮았다.

**이미 쌓인 수행 기록(`env_task_logs`)은 안 건드린다.** 거기 `points` 는 누른
순간의 값을 복사해 둔 것이라, 지금 바꾸면 지난달 점수가 소급해서 바뀐다.
점수 원장(`score_events`)도 같은 이유로 그대로 둔다.

Revision ID: env000000004
Revises: mtk000000001
"""

from typing import Sequence, Union

from alembic import op

revision: str = "env000000004"
down_revision: Union[str, Sequence[str], None] = "mtk000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 지점마다 한 벌씩 있어서 이름으로 한 번에 올린다
    op.execute("UPDATE env_items SET points = 5 WHERE name = 'TM회원관리'")


def downgrade() -> None:
    op.execute("UPDATE env_items SET points = 1 WHERE name = 'TM회원관리'")
