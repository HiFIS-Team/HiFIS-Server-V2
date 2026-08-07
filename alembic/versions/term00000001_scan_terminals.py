"""scan_terminals — 지점 출퇴근 단말 토큰

지점 카운터 PC 는 회원 등록 등에 같이 쓰는 공용 컴퓨터라, 거기에 사람 계정으로
HiFIS 를 켜 두면 누구나 급여·사내톡·조직도를 들여다볼 수 있다 (MASTER 로 켜 두면
모니터링까지 열린다). 화면 없이 포트만 듣는 프로그램이 쓸, **출퇴근 스캔만 되는**
자격증명을 만든다.

Revision ID: term00000001
Revises: dev000000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "term00000001"
down_revision: Union[str, Sequence[str], None] = "dev000000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scan_terminals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        # 원문은 저장하지 않는다 — 발급 직후 한 번만 보여준다
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("issued_by_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_scan_terminals_branch_id", "scan_terminals", ["branch_id"])
    # 들어온 토큰을 해시로 찾는다 — 매 스캔마다 타는 길이라 인덱스가 필요하다
    op.create_index(
        "ix_scan_terminals_token_hash", "scan_terminals", ["token_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_scan_terminals_token_hash", table_name="scan_terminals")
    op.drop_index("ix_scan_terminals_branch_id", table_name="scan_terminals")
    op.drop_table("scan_terminals")
