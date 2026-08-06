"""rank_overtakes — 랭킹판 추월 기록

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-08-05
"""

import sqlalchemy as sa
from alembic import op

revision = "4d5e6f7a8b9c"
down_revision = "3c4d5e6f7a8b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rank_overtakes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("metric", sa.String(20), nullable=False),
        sa.Column(
            "mover_id",
            sa.String(36),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "passed_id",
            sa.String(36),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gap", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_rank_overtakes_period", "rank_overtakes", ["period"])
    op.create_index("ix_rank_overtakes_metric", "rank_overtakes", ["metric"])
    op.create_index("ix_rank_overtakes_created", "rank_overtakes", ["created_at"])


def downgrade() -> None:
    op.drop_table("rank_overtakes")
