"""점수 원장의 원천 id 칸을 넓힌다

매출성과 점수가 `sales:{등록권id}` 로 들어가는데 42자라 36자 칸에 안 들어갔다
(2026-08-31 — 등록권마다 바로 매기게 바꾸면서 드러났다).

Revision ID: sre000000001
Revises: cmp000000001
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op

revision = "sre000000001"
down_revision = "cmp000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "score_events",
        "source_ref_id",
        existing_type=sa.String(length=36),
        type_=sa.String(length=64),
        existing_nullable=True,
    )


def downgrade() -> None:
    # 42자짜리가 남아 있으면 줄일 수 없다 — 먼저 지운다
    op.execute("DELETE FROM score_events WHERE length(source_ref_id) > 36")
    op.alter_column(
        "score_events",
        "source_ref_id",
        existing_type=sa.String(length=64),
        type_=sa.String(length=36),
        existing_nullable=True,
    )
