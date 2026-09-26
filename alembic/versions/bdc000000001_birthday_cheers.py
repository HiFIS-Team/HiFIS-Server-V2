"""생일 축하 이모지

Revision ID: bdc000000001
Revises: pts000000002
Create Date: 2026-09-27

생일 당일 모달에서 이모지를 누르면 생일자에게 푸시가 간다. 한 사람이 한 생일에
**한 번만** 보내게 (보낸 사람·받는 사람·날짜) 를 유니크로 둔다.
"""

import sqlalchemy as sa
from alembic import op

revision = "bdc000000001"
down_revision = "pts000000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "birthday_cheers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("from_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("to_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("from_id", "to_id", "day", name="uq_birthday_cheer"),
    )
    op.create_index("ix_birthday_cheers_to_id", "birthday_cheers", ["to_id"])


def downgrade() -> None:
    op.drop_index("ix_birthday_cheers_to_id", table_name="birthday_cheers")
    op.drop_table("birthday_cheers")
