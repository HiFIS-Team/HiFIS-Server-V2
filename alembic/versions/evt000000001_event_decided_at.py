"""events.decided_at · reject_reason — 일정 결재 이력

일정만 결재 이력이 없었다. 급여·월차·전자결재는 승인·반려가 다 행으로 남는데
일정은 **반려하면 지웠고**, 승인은 상태만 있어서 대표가 올려 바로 선 전사 일정과
구분이 안 됐다 (그대로 세면 달력 일정이 통째로 '승인' 칸에 선다).

- `decided_at` — 결재한 시각. **올리자마자 APPROVED 가 된 것은 null 이다**
- `reject_reason` — 반려 사유. 예전에는 알림 본문에만 실어 보내고 안 남겼다

반려는 이제 행을 남긴다(`EventStatus.REJECTED`). 대신 `GET /events` 가 그걸
빼므로 **달력은 그대로다.**

**이미 쌓인 행은 전부 null 로 둔다.** 그중 결재를 거친 것이 있는지 알 방법이
없는데(그래서 이 칸을 만드는 것이다), 임의로 채우면 대표가 올린 일정을
'승인해 줬다'고 이력에 남기게 된다. 없는 이력은 없는 채로 두는 게 맞다.

Revision ID: evt000000001
Revises: ssh000000001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "evt000000001"
down_revision: Union[str, Sequence[str], None] = "ssh000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("events", sa.Column("reject_reason", sa.Text(), nullable=True))
    # events.status 는 **네이티브 열거형**이라(`Enum(..., name="eventstatus")`)
    # 파이썬 쪽 enum 에 값을 더하는 것만으로는 DB 가 못 받는다 — 타입에도 넣는다.
    # 같은 트랜잭션에서 쓰지만 않으면 PG 12+ 는 이걸 허용한다.
    op.execute("ALTER TYPE eventstatus ADD VALUE IF NOT EXISTS 'REJECTED'")


def downgrade() -> None:
    # 되돌리면 REJECTED 인 행은 갈 곳이 없다 — 달력 조회에 그대로 섞인다.
    # **`::text` 로 비교한다** — 열거형에 그 값이 없는 상태(위 upgrade 가
    # 중간에 멈춘 DB)에서도 이 줄이 돌아야 한다.
    op.execute("DELETE FROM events WHERE status::text = 'REJECTED'")
    op.drop_column("events", "reject_reason")
    op.drop_column("events", "decided_at")
    # 열거형에서 값을 빼는 문법이 없다 — 타입을 새로 만들어 갈아끼운다
    op.execute("ALTER TYPE eventstatus RENAME TO eventstatus_old")
    op.execute("CREATE TYPE eventstatus AS ENUM ('PENDING', 'APPROVED')")
    op.execute(
        "ALTER TABLE events ALTER COLUMN status TYPE eventstatus"
        " USING status::text::eventstatus"
    )
    op.execute("DROP TYPE eventstatus_old")
