"""운동일지 — workout_logs 표와 회원의 '운동을 하는 이유'

대표 요청 (2026-08-30). 회원 상세에 수업 커리큘럼이 붙는다. PT 는 결제한
회차만큼만 쓰고, 개인 운동은 회차와 상관없이 자유롭게 쓴다.

표 안의 줄(웨이트·유산소)과 자료 묶음은 JSONB 다 — 일지 하나를 열 때 통째로
읽고 통째로 쓴다. 따로 검색하거나 집계할 일이 없어 행으로 풀 이유가 없다.

Revision ID: wko000000001
Revises: qrs000000002
Create Date: 2026-08-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "wko000000001"
down_revision: Union[str, Sequence[str], None] = "qrs000000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "members",
        sa.Column("goals", postgresql.JSONB(), nullable=False, server_default="[]"),
    )

    op.create_table(
        "workout_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("member_id", sa.String(36), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        # PT 만 붙는다 — 개인 운동은 null
        sa.Column("session_no", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("performed_on", sa.Date(), nullable=False),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("weights", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("cardio", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("media", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("trainer_feedback", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_workout_logs_member_id", "workout_logs", ["member_id"])
    op.create_index("ix_workout_logs_kind", "workout_logs", ["kind"])
    op.create_index("ix_workout_logs_author_id", "workout_logs", ["author_id"])
    op.create_index("ix_workout_logs_performed_on", "workout_logs", ["performed_on"])
    # 한 회차에 일지는 하나다 — 두 대에서 동시에 저장해도 겹치지 않게 표가 막는다
    op.create_index(
        "uq_workout_logs_pt_session",
        "workout_logs",
        ["member_id", "session_no"],
        unique=True,
        postgresql_where=sa.text("session_no IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_workout_logs_pt_session", table_name="workout_logs")
    op.drop_index("ix_workout_logs_performed_on", table_name="workout_logs")
    op.drop_index("ix_workout_logs_author_id", table_name="workout_logs")
    op.drop_index("ix_workout_logs_kind", table_name="workout_logs")
    op.drop_index("ix_workout_logs_member_id", table_name="workout_logs")
    op.drop_table("workout_logs")
    op.drop_column("members", "goals")
