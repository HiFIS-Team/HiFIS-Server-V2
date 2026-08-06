"""아바타 색 — 앱 18색 팔레트로 기존 직원 재배정 (§2.2 #14)

서버 팔레트를 앱 고르개 18색으로 교체하며, 팔레트에 없는 색을 쓰던 기존 직원
(옛 기본 #6366f1 등)을 18색에 라운드로빈으로 분산. 이미 앱 팔레트 색을 고른 직원은 보존.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-08-03 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a9b0c1d2e3'
down_revision: Union[str, Sequence[str], None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# app/services/avatar.py AVATAR_PALETTE 와 동일 (앱 _avatarColors)
PALETTE = [
    "#2F54EB", "#2B6BF3", "#5A6ACF", "#3FA7E8", "#3E8FA8", "#3EBFA5",
    "#3FA85C", "#7CA83E", "#C7952F", "#D07E2C", "#E0662B", "#CC3B33",
    "#D03A78", "#BE3ACD", "#8E3AD0", "#6B3AD0", "#3E4A5C", "#64748B",
]


def upgrade() -> None:
    conn = op.get_bind()
    # 팔레트에 없는 색(대소문자 무시)을 쓰는 직원만 대상 — 이미 고른 사람은 건드리지 않음
    stmt = sa.text(
        "SELECT id FROM employees WHERE UPPER(avatar_color) NOT IN :pal ORDER BY joined_at, id"
    ).bindparams(sa.bindparam("pal", value=PALETTE, expanding=True))
    ids = [r[0] for r in conn.execute(stmt).fetchall()]
    for i, emp_id in enumerate(ids):
        conn.execute(
            sa.text("UPDATE employees SET avatar_color = :c WHERE id = :id"),
            {"c": PALETTE[i % len(PALETTE)], "id": emp_id},
        )


def downgrade() -> None:
    # 데이터 백필이라 원복 불가 (이전 색을 보존하지 않음) — no-op
    pass
