"""전단지 배점 10 → 1

대표 결정 (2026-08-19). 돌리는 데 드는 품에 비해 배점이 커서
현수막·블로그·클레임해결과 같은 10점 자리에 있었다.

**이미 쌓인 수행 기록(`env_task_logs`)은 안 건드린다.** 거기 `points` 는 누른
순간의 값을 복사해 둔 것이라, 지금 바꾸면 지난달 점수가 소급해서 바뀐다.
점수 원장(`score_events`)도 같은 이유로 그대로 둔다.
(TM회원관리 1 → 5 를 올릴 때와 같은 규칙이다 — `env000000004`)

Revision ID: env000000006
Revises: pcmt00000001
"""

from typing import Sequence, Union

from alembic import op

revision: str = "env000000006"
down_revision: Union[str, Sequence[str], None] = "pcmt00000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 지점마다 한 벌씩 있어서 이름으로 한 번에 내린다
    op.execute("UPDATE env_items SET points = 1 WHERE name = '전단지'")


def downgrade() -> None:
    op.execute("UPDATE env_items SET points = 10 WHERE name = '전단지'")
