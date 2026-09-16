"""PT 만족도 폼 객관식 — 좋았던 점 · 보완할 점

Revision ID: ptt000000001
Revises: rkf000000001
Create Date: 2026-09-16

서술형 `request` 한 칸으로는 **"좋아요~" 만 쌓였다.** 주제를 고르게 하고
고른 자리에만 글을 받는다 (`app/services/pt_topics.py`).

**`request` 를 안 지운다** — 이 전에 받은 답이 그 칸에만 있다.
"""

import sqlalchemy as sa
from alembic import op

revision = "ptt000000001"
down_revision = "rkf000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pt_surveys", sa.Column("praise", sa.JSON(), nullable=True))
    op.add_column("pt_surveys", sa.Column("improve", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("pt_surveys", "improve")
    op.drop_column("pt_surveys", "praise")
