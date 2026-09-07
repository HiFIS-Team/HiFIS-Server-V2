"""추첨 당첨자를 세 명으로 — winner_index → winner_indexes

한 달에 한 명을 뽑던 것을 **세 명**으로 바꾼다 (2026-09-01 대표 결정).
이미 뽑아 둔 행이 있으면 그 한 명을 배열 첫 칸으로 옮긴다.

Revision ID: drw000000002
Revises: drw000000001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "drw000000002"
down_revision = "drw000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "draws",
        sa.Column(
            "winner_indexes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    # 이미 뽑힌 한 명은 첫 칸으로 — 그 사람 당첨을 없던 일로 만들면 안 된다
    op.execute(
        "UPDATE draws SET winner_indexes = jsonb_build_array(winner_index) "
        "WHERE winner_index IS NOT NULL"
    )
    op.drop_column("draws", "winner_index")


def downgrade() -> None:
    op.add_column("draws", sa.Column("winner_index", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE draws SET winner_index = (winner_indexes->>0)::int "
        "WHERE jsonb_array_length(winner_indexes) > 0"
    )
    op.drop_column("draws", "winner_indexes")
