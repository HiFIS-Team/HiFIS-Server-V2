"""env_items.sort_order 재배치 — 흐름별 그룹 순서 (§31)

기존 sort_order 는 옛 순서(현수막이 청소 사이, 화장실청소가 뒤로). 새 그룹 순서로 재백필.
커스텀 항목(1000)은 건드리지 않는다.

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-08-03 08:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0c1d2e3f4a5'
down_revision: Union[str, Sequence[str], None] = 'a9b0c1d2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# BASE_ENV_ITEMS 새 순서 (app/api/scoring/env.py 와 동일)
NEW_ORDER = [
    "빨래정리", "건조기", "세탁",
    "구역청소", "복도청소", "화장실청소", "락커정리",
    "남탈부스", "남탈청소", "여탈부스", "여탈청소",
    "기구관리",
    "회원지도", "TM회원관리", "클레임해결",
    "현수막", "족자", "전단지", "블로그", "게시물", "스토리",
    "기타",
]


def upgrade() -> None:
    for i, name in enumerate(NEW_ORDER):
        op.execute(
            sa.text("UPDATE env_items SET sort_order = :o WHERE name = :n").bindparams(o=i, n=name)
        )


def downgrade() -> None:
    # 순서 데이터 재배치라 원복 불필요 — no-op
    pass
