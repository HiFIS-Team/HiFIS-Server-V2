"""project_requests — 수정·삭제 결재를 같은 테이블에 태운다

"수정 및 삭제는 마스터의 허가가 있어야 가능하다" (2026-08-14). 담당자가 그냥
고치고 그냥 지우던 것을 기한 연장이 쓰던 결재 통로에 얹었다.

- `new_due` 를 **nullable 로** — EDIT·DELETE 는 기한과 무관하다
- `payload` 추가 — EDIT 이 "이렇게 바꾸겠다"를 담는다 (`title`·`purpose`·`color`)

`type` 은 네이티브 열거형이 아니라 `SAEnum(..., native_enum=False)` 라 문자열
길이 검사만 있다. 그래서 EDIT·DELETE 를 더하는 데 DB 쪽 손댈 것이 없다
(events.status 와 다른 점이다 — 그쪽은 ALTER TYPE 이 필요했다).

**이미 쌓인 행은 그대로다.** 전부 EXTENSION·OVERDUE 라 `new_due` 가 차 있고
`payload` 는 비어 있는 게 맞다.

Revision ID: prq000000001
Revises: evt000000001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "prq000000001"
down_revision: Union[str, Sequence[str], None] = "evt000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("project_requests", "new_due", existing_type=sa.DateTime(timezone=True), nullable=True)
    op.add_column("project_requests", sa.Column("payload", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    # 되돌리면 new_due 가 빈 행(EDIT·DELETE)은 NOT NULL 을 못 지킨다 — 먼저 치운다
    op.execute("DELETE FROM project_requests WHERE new_due IS NULL")
    op.drop_column("project_requests", "payload")
    op.alter_column("project_requests", "new_due", existing_type=sa.DateTime(timezone=True), nullable=False)
