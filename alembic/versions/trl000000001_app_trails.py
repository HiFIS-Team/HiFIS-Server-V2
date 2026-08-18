"""앱 사용 기록 — app_trails

**어느 화면을 열었고 무엇을 봤는지**를 남긴다 (2026-08-18 대표 결정).

기존 두 로그가 못 담던 자리를 채운다.

| | 무엇을 남기나 |
|---|---|
| `access_logs` | 들어왔다 / 못 들어왔다 |
| `audit_logs` | **한 일** (등록·수정·삭제) |
| **`app_trails`** | **본 것** (화면 이동·열람) |

화면을 옮기는 것은 서버를 안 거쳐서 미들웨어로는 잡을 수 없다. 그래서
앱이 메모리에 쌓아 두었다가 **묶어서** 올린다 (`POST /trails`).

인덱스를 `(employee_id, at)` 로 묶어 둔다 — 조회가 늘 "누가, 언제" 라서
따로 걸면 한쪽만 타고 나머지를 훑는다. 이 표가 제일 빨리 늘어나는 자리다.

보존 90일 — 접속·활동 로그와 같은 파기 잡을 탄다.

Revision ID: trl000000001
Revises: env000000005
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "trl000000001"
down_revision: Union[str, None] = "env000000005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_trails",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("employee_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("screen", sa.String(length=60), nullable=False),
        sa.Column("target", sa.String(length=120), nullable=True),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_trails_employee_id", "app_trails", ["employee_id"])
    op.create_index("ix_app_trails_kind", "app_trails", ["kind"])
    op.create_index("ix_app_trails_at", "app_trails", ["at"])
    # 조회가 늘 "이 사람 것을 최신순으로" 라 묶어 둔다
    op.create_index("ix_app_trails_emp_at", "app_trails", ["employee_id", "at"])
    # 파기 잡이 도는 기준
    op.create_index("ix_app_trails_created_at", "app_trails", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_app_trails_created_at", table_name="app_trails")
    op.drop_index("ix_app_trails_emp_at", table_name="app_trails")
    op.drop_index("ix_app_trails_at", table_name="app_trails")
    op.drop_index("ix_app_trails_kind", table_name="app_trails")
    op.drop_index("ix_app_trails_employee_id", table_name="app_trails")
    op.drop_table("app_trails")
