"""환경정비 배점 조정 — 빨래정리 3→2, 화장실청소 5→2

2026-08-13 대표 결정. 자주 하는 항목이라 다른 것과 무게를 맞춘다.

**이미 쌓인 기록은 안 건드린다** (앞으로만). `env_task_logs` 가 수행 시점의
점수를 복사해 두는 구조라, 여기서 `env_items` 만 바꾸면 지난 기록은 그대로
남고 다음 수행부터 새 배점이 붙는다.

Revision ID: env000000002
Revises: fst000000001
"""

from typing import Sequence, Union

from alembic import op

revision: str = "env000000002"
down_revision: Union[str, Sequence[str], None] = "fst000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (항목 이름, 새 점수, 되돌릴 점수)
_CHANGES = [("빨래정리", 2, 3), ("화장실청소", 2, 5)]


def upgrade() -> None:
    for name, new, _old in _CHANGES:
        op.execute(f"UPDATE env_items SET points = {new} WHERE name = '{name}'")


def downgrade() -> None:
    for name, _new, old in _CHANGES:
        op.execute(f"UPDATE env_items SET points = {old} WHERE name = '{name}'")
