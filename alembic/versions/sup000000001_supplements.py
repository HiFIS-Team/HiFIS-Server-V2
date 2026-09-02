"""영양제 — supplements 표

대표 요청 (2026-09-03). 회원 상세의 운동일지·개인 운동 아래에 영양제 칸이
붙는다. 트레이너가 쓰던 표(영양제/얼마나/언제/왜/기억하기)를 그대로 옮겼다.

**JSONB 로 안 묶는다.** 일지는 한 장을 통째로 열고 통째로 저장하지만 영양제는
줄 하나가 곧 하나의 권유라 따로 고치고 따로 지운다.

Revision ID: sup000000001
Revises: drw000000004
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sup000000001"
down_revision: Union[str, Sequence[str], None] = "drw000000004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supplements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("member_id", sa.String(36), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("dose", sa.String(80), nullable=False, server_default=""),
        sa.Column("timing", sa.String(80), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        # 트레이너가 세운 차례 — 먹는 순서대로 두려고 손으로 옮길 수 있다
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # 회원 상세를 열 때마다 이 회원 것만 차례대로 읽는다
    op.create_index("ix_supplements_member_id", "supplements", ["member_id", "sort_order"])
    op.create_index("ix_supplements_author_id", "supplements", ["author_id"])


def downgrade() -> None:
    op.drop_index("ix_supplements_author_id", table_name="supplements")
    op.drop_index("ix_supplements_member_id", table_name="supplements")
    op.drop_table("supplements")
