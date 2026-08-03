"""친절 설문 별점 (kindness_surveys.stars)

앱 랭킹의 '리뷰 27건 · ★4.5' 가 이 값을 쓴다.
**선택 입력**이라 안 받은 설문은 null 이고 평균에서 빠진다.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-08-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5b6c7d8e9f0'
down_revision: Union[str, Sequence[str], None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'kindness_surveys',
        sa.Column('stars', sa.SmallInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('kindness_surveys', 'stars')
