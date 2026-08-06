"""payday_policies — 지점×직급별 급여 지급일·주기

지급일이 전 지점·전 직급 말일 고정이었다. 실제 규칙은 코드 주석에만 있었다:
화순 = 말일 / 동광주·첨단 = FC 말일 · 나머지 익월 10일.

**측정 시작일도 같이 넣는다** — 앱을 켜기 전 실적을 급여로 잡으면 안 되므로
말일 쪽은 2026-09-01, 익월 10일 쪽은 2026-09-10 부터 잰다.

Revision ID: 8b9c0d1e2f3a
Revises: 7a8b9c0d1e2f
"""

from datetime import date, datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

revision: str = "8b9c0d1e2f3a"
down_revision: Union[str, Sequence[str], None] = "7a8b9c0d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: 익월 10일로 가는 지점 이름 (그 안에서 FC 만 말일로 되돌린다)
_TENTH_BRANCHES = ("첨단", "동광주")

_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)
_START_MONTHLY = date(2026, 9, 1)  # 말일 지급 — 첫 주기 9/1~9/30
_START_TENTH = date(2026, 9, 10)  # 익월 10일 지급 — 첫 주기 9/10~10/9


def upgrade() -> None:
    op.create_table(
        "payday_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("rank", sa.String(20), nullable=True),
        sa.Column("day", sa.Integer(), nullable=True),
        sa.Column("next_month", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_payday_policies_branch_id", "payday_policies", ["branch_id"])
    op.create_index("ix_payday_policies_rank", "payday_policies", ["rank"])

    # 명세서는 만들 때의 지급일을 그대로 들고 있는다 — 나중에 규칙이 바뀌어도
    # 이미 준 돈의 날짜가 따라 움직이면 안 된다. (null = 규칙 이전 명세서)
    op.add_column("payslips", sa.Column("pay_date", sa.Date(), nullable=True))

    conn = op.get_bind()
    rows = [
        # 전사 기본 — 말일 지급(당월). 화순이 이걸 탄다.
        {
            "id": str(uuid.uuid4()),
            "branch_id": None,
            "rank": None,
            "day": None,
            "next_month": False,
            "starts_on": _START_MONTHLY,
            "effective_from": _EPOCH,
        }
    ]
    for name in _TENTH_BRANCHES:
        branch_id = conn.execute(
            sa.text("SELECT id FROM branches WHERE name = :name"), {"name": name}
        ).scalar()
        if branch_id is None:
            continue  # 아직 없는 지점이면 나중에 넣는다 (전사 기본을 탄다)
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "branch_id": branch_id,
                "rank": None,
                "day": 10,
                "next_month": True,
                "starts_on": _START_TENTH,
                "effective_from": _EPOCH,
            }
        )
        # 같은 지점의 FC 만 말일로 되돌린다 (좁은 쪽이 이긴다)
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "branch_id": branch_id,
                "rank": "FC",
                "day": None,
                "next_month": False,
                "starts_on": _START_MONTHLY,
                "effective_from": _EPOCH,
            }
        )

    conn.execute(
        sa.text(
            "INSERT INTO payday_policies "
            "(id, branch_id, rank, day, next_month, starts_on, effective_from) VALUES "
            "(:id, :branch_id, :rank, :day, :next_month, :starts_on, :effective_from)"
        ),
        rows,
    )


def downgrade() -> None:
    op.drop_column("payslips", "pay_date")
    op.drop_index("ix_payday_policies_rank", table_name="payday_policies")
    op.drop_index("ix_payday_policies_branch_id", table_name="payday_policies")
    op.drop_table("payday_policies")
