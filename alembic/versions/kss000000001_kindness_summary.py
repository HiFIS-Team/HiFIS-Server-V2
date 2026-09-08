"""컴플레인 한 줄 요약 칸 — 매장 TV 가 자르는 것을 막는다 (2026-09-08)

Revision ID: kss000000001
Revises: sup000000001
"""

import sqlalchemy as sa
from alembic import op

revision = "kss000000001"
down_revision = "sup000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 이미 쌓인 행은 전부 null 이다 — 그때는 요약을 만든 적이 없으므로
    # TV 가 원문을 쓴다. 거슬러 만들지 않는다 (돈이 들고, 이미 벽에 걸렸던
    # 문장이 어느 날 다른 말로 바뀐다).
    op.add_column("kindness_surveys", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("kindness_surveys", "summary")
