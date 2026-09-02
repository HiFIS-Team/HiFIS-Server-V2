"""추첨 영상 포스터 — 앱 화면 히어로에 쓸 한 장

영상 마지막 프레임(폭죽이 걷힌 시상대)을 같이 뽑아 둔다. 앱이 그걸 크게
띄우고, 영상은 눌렀을 때 튼다 — 앱 안에 재생기를 안 넣으려고 그렇게 한다.

Revision ID: drw000000004
Revises: drw000000003
"""

import sqlalchemy as sa
from alembic import op

revision = "drw000000004"
down_revision = "drw000000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("draws", sa.Column("poster_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("draws", "poster_path")
