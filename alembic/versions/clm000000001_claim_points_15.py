"""클레임해결 배점 10 → 15

컴플레인을 끝까지 처리한 값이라 다른 환경정비 항목보다 높게 둔다
(2026-08-31 대표 요청). 지점마다 이미 심겨 있는 행도 같이 올린다 —
`_ensure_base_items` 는 **없을 때만** 만들기 때문에 코드만 고치면
기존 지점은 10 그대로다.

**이미 쌓인 수행 기록(EnvTaskLog)의 점수는 안 건드린다.** 그때 매긴 값이
그때의 배점이라, 소급해서 올리면 지난 달 랭킹이 흔들린다.

Revision ID: clm000000001
Revises: sre000000001
Create Date: 2026-08-31
"""

from alembic import op

revision = "clm000000001"
down_revision = "sre000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE env_items SET points = 15 WHERE name = '클레임해결'")


def downgrade() -> None:
    op.execute("UPDATE env_items SET points = 10 WHERE name = '클레임해결'")
