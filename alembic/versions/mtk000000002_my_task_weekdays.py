"""개인 업무에 돌아오는 요일 (2026-08-20)

금요일에만 하는 대청소를 넣으면 월~목에도 목록에 서고, 안 누른 그 나흘이
전부 누락으로 잡혔다. 항목마다 돌아오는 요일을 갖게 한다.

**기존 항목은 전부 매일(1~7)로 채운다.** 그때는 '매일 반복'이 전제였으므로
그게 그 사람들이 정한 값이다 — 비워 두면 있던 업무가 통째로 사라진다.

Revision ID: mtk000000002
Revises: env000000006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "mtk000000002"
down_revision = "env000000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "my_tasks",
        sa.Column(
            "weekdays",
            postgresql.ARRAY(sa.Integer()),
            nullable=False,
            server_default="{1,2,3,4,5,6,7}",
        ),
    )


def downgrade() -> None:
    op.drop_column("my_tasks", "weekdays")
