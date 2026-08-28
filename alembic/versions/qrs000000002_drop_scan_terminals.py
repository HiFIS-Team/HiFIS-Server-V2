"""지점 출퇴근 단말 테이블 제거 — 카운터 QR 로 갈아탔다

대표 결정 (2026-08-28). 카운터 PC 를 없애고 매장에 붙인 QR 을 직원 폰이
읽는 방식으로 바꿨다 (`qrs000000001`). 단말 토큰으로 들어오던 길이 통째로
사라져서 표를 남길 이유가 없다.

**되돌리기(`downgrade`)는 표만 되살린다.** 발급했던 토큰은 해시로만 갖고
있어서 복구할 수 없다 — 되돌릴 일이 생기면 지점마다 새로 발급해야 한다.

Revision ID: qrs000000002
Revises: qrs000000001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "qrs000000002"
down_revision: Union[str, Sequence[str], None] = "qrs000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("scan_terminals")


def downgrade() -> None:
    op.create_table(
        "scan_terminals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("issued_by_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scanner_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scanner_port", sa.String(20), nullable=True),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
