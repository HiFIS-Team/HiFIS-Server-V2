"""지난달 랭킹판을 통째로 굳혀 두는 표

Revision ID: rkf000000001
Revises: tvh000000001
Create Date: 2026-09-16

랭킹은 매번 원본(등록권 결제액·점수 원장)에서 다시 셌다. 그래서 **지난
데이터를 고치면 지난 랭킹이 같이 움직였다** — 9월에 잘못 넣은 등록권을
0원으로 고쳤더니 그 달 매출 순위가 바뀌었다. 전달 통계는 그 달로 끝나야 한다.

판을 **통째로** 담는다(`rows`). 항목이 여섯이고 앞으로 늘 수 있는데 칸으로
쪼개 두면 항목이 늘 때마다 표를 고쳐야 한다.

**이미 지나간 달은 여기서 안 채운다** — 지점 목록을 읽고 판을 계산해야 해서
마이그레이션에서 할 일이 아니다. 배포 뒤 `freeze_previous_month(period=...)`
를 한 번 불러 채운다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "rkf000000001"
down_revision: Union[str, Sequence[str], None] = "tvh000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ranking_freezes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("period", sa.String(7), nullable=False, index=True),
        # null 이면 전 지점 — 지점별로 순위가 다시 매겨져서 따로 찍는다
        sa.Column("branch_id", sa.String(36), nullable=True),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("period", "branch_id", name="uq_ranking_freeze_scope"),
    )


def downgrade() -> None:
    op.drop_table("ranking_freezes")
