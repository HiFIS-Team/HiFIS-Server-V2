"""고용 형태(정규직·알바) + 시급 정책

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-08-05
"""

import sqlalchemy as sa
from alembic import op

revision = "3c4d5e6f7a8b"
down_revision = "2b3c4d5e6f7a"
branch_labels = None
depends_on = None

# 2026년 최저임금 — 첫 정책 한 줄을 여기서 심는다
_INITIAL_WAGE = 10320


def upgrade() -> None:
    # 기존 직원은 전부 정규직으로 본다 (알바는 인사 정보에서 바꾼다)
    op.add_column(
        "employees",
        sa.Column(
            "employment_type",
            sa.String(20),
            nullable=False,
            server_default="FULL_TIME",
        ),
    )

    op.create_table(
        "hourly_wage_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("wage", sa.Integer(), nullable=False),
        sa.Column(
            "branch_id",
            sa.String(36),
            sa.ForeignKey("branches.id"),
            nullable=True,
        ),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_hourly_wage_effective", "hourly_wage_policies", ["effective_from"]
    )

    # 전사 기본 시급 한 줄 — 없으면 알바 급여를 못 뽑는다.
    # 아주 옛 날짜로 심어야 지난 달 급여도 이 값으로 계산된다.
    op.execute(
        sa.text(
            "INSERT INTO hourly_wage_policies (id, wage, branch_id, effective_from) "
            "VALUES (:id, :wage, NULL, '1970-01-01T00:00:00+00:00')"
        ).bindparams(id="00000000-0000-4000-8000-000000000001", wage=_INITIAL_WAGE)
    )


def downgrade() -> None:
    op.drop_table("hourly_wage_policies")
    op.drop_column("employees", "employment_type")
