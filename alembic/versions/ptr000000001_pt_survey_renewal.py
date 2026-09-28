"""PT 만족도 — 답을 안 낸 채로 재등록한 등록권

Revision ID: ptr000000001
Revises: pyr000000001
Create Date: 2026-09-28

미응답 회원이 재등록하면 그 설문을 '연장됐어요'(`renew = RENEWED`)로 닫는다.
예상 매출을 옛 등록권이 아니라 **재등록 금액**으로 세려고 그 등록권을 가리킨다.
`renew` 는 문자열 칸(`native_enum=False`)이라 값을 더하는 데 마이그레이션이 필요 없다.
"""

import sqlalchemy as sa
from alembic import op

revision = "ptr000000001"
down_revision = "pyr000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pt_surveys",
        sa.Column(
            "renewal_id",
            sa.String(36),
            sa.ForeignKey("registrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("pt_surveys", "renewal_id")
