"""OT 신청

Revision ID: otr000000001
Revises: gol000000002
Create Date: 2026-09-28

네이버 플레이스·전단지 QR 로 들어온 OT 신청 → 배정 → 수락 → 확정
(`app/models/members/ot_request.py`).
"""

import sqlalchemy as sa
from alembic import op

revision = "otr000000001"
down_revision = "gol000000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ot_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("gender", sa.String(10), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("assignee_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("assigned_by_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("sms_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ot_requests_branch_id", "ot_requests", ["branch_id"])
    op.create_index("ix_ot_requests_phone", "ot_requests", ["phone"])
    op.create_index("ix_ot_requests_status", "ot_requests", ["status"])
    op.create_index("ix_ot_requests_assignee_id", "ot_requests", ["assignee_id"])


def downgrade() -> None:
    op.drop_table("ot_requests")
