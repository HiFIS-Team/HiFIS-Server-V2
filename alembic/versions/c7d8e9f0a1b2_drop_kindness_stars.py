"""친절 설문 별점 제거 (kindness_surveys.stars)

`a5b6c7d8e9f0` 에서 넣었던 칸을 되돌린다.

**쓰는 데가 없어서 뺀다.** 앱 랭킹 목업에 `★4.5` 라고 적혀 있던 것을
채우려고 만든 칸인데, 그 숫자는 처음부터 손으로 박아 둔 값이었고
설문에 별점 문항도 없다. 친절 점수는 설문 한 건당 10점으로 이미 나온다.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-08-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, Sequence[str], None] = 'b6c7d8e9f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('kindness_surveys', 'stars')


def downgrade() -> None:
    op.add_column(
        'kindness_surveys',
        sa.Column('stars', sa.SmallInteger(), nullable=True),
    )
