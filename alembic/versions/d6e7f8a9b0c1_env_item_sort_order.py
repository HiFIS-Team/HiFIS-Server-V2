"""env_items.sort_order (환경정비 고정 순서)

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-03 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# BASE_ENV_ITEMS 와 동일한 순서 (app/api/scoring/env.py) — 기존 행 백필용
BASE_NAMES = [
    "빨래정리", "건조기", "세탁", "구역청소", "현수막", "복도청소", "락커정리",
    "남탈부스", "남탈청소", "여탈부스", "여탈청소", "기구관리", "회원지도",
    "블로그", "족자", "게시물", "스토리", "클레임해결", "전단지",
    "화장실청소", "TM회원관리", "기타",
]


def upgrade() -> None:
    op.add_column('env_items', sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False))
    # 기존 데이터 백필: 커스텀 항목은 맨 아래(1000), 기본 항목은 목록 순서대로
    op.execute("UPDATE env_items SET sort_order = 1000")
    for i, name in enumerate(BASE_NAMES):
        op.execute(
            sa.text("UPDATE env_items SET sort_order = :o WHERE name = :n").bindparams(o=i, n=name)
        )


def downgrade() -> None:
    op.drop_column('env_items', 'sort_order')
