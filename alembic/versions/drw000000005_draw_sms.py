"""추첨 당첨 문자 — 보낸 때를 남긴다

잡이 두 번 돌거나 손으로 다시 불러도 당첨자에게 문자가 두 번 가지 않게.

Revision ID: drw000000005
Revises: drw000000004
"""

import sqlalchemy as sa
from alembic import op

revision = "drw000000005"
down_revision = "drw000000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("draws", sa.Column("sms_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("draws", "sms_sent_at")
