"""프로젝트 완료 알림 멱등 표시 — projects.completed_notified_at

완료(100%)를 대표·관리자에게 알리는데, 완료 정산(`_settle_completion`)은
진행률을 건드릴 때마다 불린다. 이 표시가 없으면 **이미 완료된 프로젝트를
고칠 때마다 '완료' 알림이 다시 나간다.** 누락 알림(`overdue_notified_at`)과
같은 방식이다.

이미 완료된 프로젝트는 **보낸 것으로 채워 둔다** — 안 그러면 다음에 그 프로젝트를
건드리는 순간 몇 달 지난 완료 알림이 한꺼번에 나간다.

Revision ID: prj000000001
Revises: vis000000001
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "prj000000001"
down_revision: Union[str, Sequence[str], None] = "vis000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("completed_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 이미 100% 인 것은 '알림 보냄'으로 표시 (과거분을 다시 알리지 않는다)
    op.execute(
        "UPDATE projects SET completed_notified_at = now() WHERE progress >= 100"
    )


def downgrade() -> None:
    op.drop_column("projects", "completed_notified_at")
