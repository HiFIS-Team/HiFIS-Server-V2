"""매장 TV 추첨 — draws 표

대표 요청 (2026-09-01). 전달에 친절도 설문을 낸 회원 중에서 달마다 한 명을
뽑고, 매장 TV 가 게임(핀볼·사다리·룰렛)으로 굴려 보여준다.

참가자를 `entries` 에 통째로 베껴 둔다 — 설문이 나중에 지워져도 지난 추첨
화면이 그대로 재생돼야 한다. `seed` 는 화면이 굴러가는 모양만 정하고
**당첨자는 `winner_index` 에 이미 박혀 있다.**

Revision ID: drw000000001
Revises: wko000000001
Create Date: 2026-09-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "drw000000001"
down_revision: Union[str, Sequence[str], None] = "wko000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "draws",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        # 이벤트가 열리는 달 — 대상은 **그 전달** 설문이다
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("game", sa.String(16), nullable=False),
        sa.Column("seed", sa.String(32), nullable=False),
        sa.Column("entries", postgresql.JSONB(), nullable=False, server_default="[]"),
        # 참가자가 없으면 null (그 달 설문이 한 건도 없던 지점)
        sa.Column("winner_index", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_draws_branch_id", "draws", ["branch_id"])
    op.create_index("ix_draws_period", "draws", ["period"])
    # 잡이 두 번 돌아도 두 번 뽑히지 않게
    op.create_unique_constraint("uq_draws_branch_period", "draws", ["branch_id", "period"])


def downgrade() -> None:
    op.drop_constraint("uq_draws_branch_period", "draws", type_="unique")
    op.drop_index("ix_draws_period", table_name="draws")
    op.drop_index("ix_draws_branch_id", table_name="draws")
    op.drop_table("draws")
