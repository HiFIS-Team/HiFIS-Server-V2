"""화순 지점 추가 — 지점 분리(c1d2e3f4a5b6) 때 빠져 있었다

약관·개인정보처리방침·급여 규칙(8b9c0d1e2f3a)에는 화순이 계속 들어 있었는데
`branches` 에는 첨단·동광주만 만들어져 화순 소속을 고를 수가 없었다.

- 공유 묶음은 `A` — 첨단과 서로 본다 (bgrp00000001 의 규칙 그대로).
- 급여 지급일은 따로 넣지 않는다. 화순은 전사 기본(말일)을 그대로 탄다.
- 환경정비 항목은 첫 조회 때 `_ensure_base_items` 가 알아서 심는다.

Revision ID: hsn000000001
Revises: tms000000001
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.tokens import public_token

revision: str = "hsn000000001"
down_revision: Union[str, Sequence[str], None] = "tms000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAME = "화순"
_SHARE_GROUP = "A"


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM branches WHERE name = :n"), {"n": _NAME}
    ).fetchone()
    if exists is not None:
        return
    conn.execute(
        sa.text(
            "INSERT INTO branches (id, name, type, share_group, survey_token, tv_token) "
            "VALUES (:id, :n, 'BRANCH', :g, :s, :t)"
        ),
        {
            "id": str(uuid.uuid4()),
            "n": _NAME,
            "g": _SHARE_GROUP,
            "s": public_token(),
            "t": public_token(),
        },
    )


def downgrade() -> None:
    # 사람이 붙은 뒤 지우면 소속이 끊긴다 — 인원 0 일 때만 되돌린다.
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id FROM branches WHERE name = :n"), {"n": _NAME}
    ).fetchone()
    if row is None:
        return
    branch_id = row[0]
    if conn.execute(
        sa.text("SELECT count(*) FROM employees WHERE branch_id = :b"), {"b": branch_id}
    ).scalar():
        raise RuntimeError("화순에 직원이 있어 되돌리지 않습니다")
    conn.execute(sa.text("DELETE FROM env_task_logs WHERE branch_id = :b"), {"b": branch_id})
    conn.execute(sa.text("DELETE FROM env_items WHERE branch_id = :b"), {"b": branch_id})
    conn.execute(sa.text("DELETE FROM branches WHERE id = :b"), {"b": branch_id})
