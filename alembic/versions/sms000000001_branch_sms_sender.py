"""지점 문자 발신번호 · 컴플레인 문자 발송 시각 (2026-09-08)

Revision ID: sms000000001
Revises: kss000000001
"""

import sqlalchemy as sa
from alembic import op

revision = "sms000000001"
down_revision = "kss000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 지점마다 따로 둔다 — 회원이 되걸면 그 매장에 닿아야 한다.
    # **기존 지점은 전부 null 이다** = 넣기 전까지 문자를 안 보낸다.
    op.add_column("branches", sa.Column("sms_sender", sa.String(20), nullable=True))
    # 완료가 두 자리에서 찍혀서, 안 막으면 문자가 두 통 간다
    op.add_column(
        "kindness_surveys",
        sa.Column("sms_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("kindness_surveys", "sms_sent_at")
    op.drop_column("branches", "sms_sender")
