"""지난달 랭킹 1위 축하 이모지

Revision ID: rkc000000001
Revises: drw000000005
Create Date: 2026-10-01

축하 페이지에서 1위에게 이모지를 보내면 푸시가 간다. 한 사람이 한 1위에게
그달 **한 번만** 보내게 (보낸 사람·받는 사람·달) 을 유니크로 둔다.
"""

import sqlalchemy as sa
from alembic import op

revision = "rkc000000001"
down_revision = "drw000000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ranking_cheers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("from_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("to_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("from_id", "to_id", "period", name="uq_ranking_cheer"),
    )
    op.create_index("ix_ranking_cheers_to_id", "ranking_cheers", ["to_id"])


def downgrade() -> None:
    op.drop_index("ix_ranking_cheers_to_id", table_name="ranking_cheers")
    op.drop_table("ranking_cheers")
