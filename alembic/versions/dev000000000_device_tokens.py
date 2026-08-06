"""device_tokens — 앱 푸시(APNs) 기기 토큰

지금까지 푸시는 웹푸시(VAPID)뿐이라 **앱에는 한 건도 안 갔다**
(구독 32건이 전부 예전 Safari 흔적, 발송은 403 실패 — backend-gap 78번).
앱이 받은 기기 토큰을 담을 자리를 만든다.

Revision ID: dev000000000
Revises: 9c0d1e2f3a4b
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "dev000000000"
down_revision: Union[str, Sequence[str], None] = "9c0d1e2f3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("token", sa.String(200), nullable=False),
        sa.Column("platform", sa.String(10), nullable=False, server_default="IOS"),
        sa.Column("sandbox", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_device_tokens_employee_id", "device_tokens", ["employee_id"])
    # 기기당 한 줄 — 같은 폰에 다른 사람이 로그인하면 주인만 바뀐다
    op.create_index("ix_device_tokens_token", "device_tokens", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_device_tokens_token", table_name="device_tokens")
    op.drop_index("ix_device_tokens_employee_id", table_name="device_tokens")
    op.drop_table("device_tokens")
