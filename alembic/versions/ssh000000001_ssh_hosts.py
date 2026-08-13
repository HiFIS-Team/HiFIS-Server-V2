"""ssh_hosts — SSH 로 들어온 적 있는 IP

SSH 접속 알림을 **처음 보는 곳에서만** 내려고 IP 를 기억한다 (2026-08-13 결정).
세션마다 알리던 것이 개발자가 서버를 한 번 살펴보는 동안 열 건씩 쏟아졌다.

지역도 여기 캐시한다 — 같은 IP 를 두 번 조회할 이유가 없다.

Revision ID: ssh000000001
Revises: env000000002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ssh000000001"
down_revision: Union[str, Sequence[str], None] = "env000000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ssh_hosts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ip", sa.String(45), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ssh_hosts_ip", "ssh_hosts", ["ip"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_ssh_hosts_ip", table_name="ssh_hosts")
    op.drop_table("ssh_hosts")
