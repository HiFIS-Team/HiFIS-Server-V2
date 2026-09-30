"""OT 신청 — 운동 목적 칸을 200자로

Revision ID: otr000000002
Revises: otr000000001
Create Date: 2026-09-29

`기구 사용법` · `기타` 보기가 붙었다. `기타` 는 손님이 적은 내용까지
`기타 · 적은 내용` 으로 담아서 40자로는 모자란다.
"""

import sqlalchemy as sa
from alembic import op

revision = "otr000000002"
down_revision = "otr000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("ot_requests", "purpose", type_=sa.String(200), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("ot_requests", "purpose", type_=sa.String(40), existing_nullable=False)
