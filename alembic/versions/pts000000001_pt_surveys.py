"""PT 만족도 폼 (신규 7회차) — pt_surveys

Revision ID: pts000000001
Revises: mtk000000002
Create Date: 2026-08-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "pts000000001"
down_revision: Union[str, Sequence[str], None] = "mtk000000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pt_surveys",
        sa.Column("id", sa.String(36), primary_key=True),
        # 등록권당 하나 — 7회차는 한 번뿐이다
        sa.Column(
            "registration_id",
            sa.String(36),
            sa.ForeignKey("registrations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("member_id", sa.String(36), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("trainer_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("token", sa.String(32), nullable=False, unique=True),
        sa.Column("session_no", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("satisfaction", sa.Integer(), nullable=True),
        sa.Column("request", sa.Text(), nullable=True),
        sa.Column("renew", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pt_surveys_registration_id", "pt_surveys", ["registration_id"])
    op.create_index("ix_pt_surveys_member_id", "pt_surveys", ["member_id"])
    op.create_index("ix_pt_surveys_trainer_id", "pt_surveys", ["trainer_id"])
    op.create_index("ix_pt_surveys_token", "pt_surveys", ["token"])


def downgrade() -> None:
    op.drop_index("ix_pt_surveys_token", table_name="pt_surveys")
    op.drop_index("ix_pt_surveys_trainer_id", table_name="pt_surveys")
    op.drop_index("ix_pt_surveys_member_id", table_name="pt_surveys")
    op.drop_index("ix_pt_surveys_registration_id", table_name="pt_surveys")
    op.drop_table("pt_surveys")
