"""개인 업무에 입력 칸 — 체크할 때 값을 받는다

주간 신규·재등록 수처럼 **체크와 함께 받아야 하는 값**이 있다 (2026-08-31 요청).
환경정비의 현수막 사진은 항목 이름을 코드에 박아 뒀는데(`{'현수막','족자'}`),
개인 업무는 본인이 이름을 지어 만드는 목록이라 그 방식을 못 쓴다.

| 생긴 것 | 담는 것 |
|---|---|
| `my_tasks.fields` | 받을 칸 — `[{"name": "신규", "kind": "NUMBER"}, ...]` |
| `my_task_checks.values` | 그날 적어 넣은 값 — `{"신규": 3, "재등록": 5}` |

**값을 업무가 아니라 체크에 담는다.** 날마다 달라지는 값이라 업무에 담으면
지난주에 적은 것이 이번주 값으로 덮인다.

기존 업무는 전부 빈 배열이다 — 그때는 이런 개념이 없었으니 칸을 안 둔 것이 맞다.

Revision ID: mtf000000001
Revises: atc000000001
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "mtf000000001"
down_revision = "atc000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "my_tasks",
        sa.Column("fields", JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "my_task_checks",
        sa.Column("values", JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("my_task_checks", "values")
    op.drop_column("my_tasks", "fields")
