"""api_metrics · anomalies — 성능 지표와 이상행동 감지

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-08-04
"""

import sqlalchemy as sa
from alembic import op

revision = "2b3c4d5e6f7a"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("route", sa.String(200), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("client_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sum_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("max_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("b5", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("b10", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("b25", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("b50", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("b100", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("b250", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("b500", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("b1000", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("b3000", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("over", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("minute", "method", "route", name="uq_api_metrics_slot"),
    )
    op.create_index("ix_api_metrics_minute", "api_metrics", ["minute"])
    op.create_index("ix_api_metrics_route", "api_metrics", ["route"])

    op.create_table(
        "anomalies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column(
            "employee_id",
            sa.String(36),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("detail", sa.String(300), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("window_key", sa.String(200), nullable=False, unique=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by_id",
            sa.String(36),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_anomalies_kind", "anomalies", ["kind"])
    op.create_index("ix_anomalies_employee_id", "anomalies", ["employee_id"])
    op.create_index("ix_anomalies_created_at", "anomalies", ["created_at"])


def downgrade() -> None:
    op.drop_table("anomalies")
    op.drop_table("api_metrics")
