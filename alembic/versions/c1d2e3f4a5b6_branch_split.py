"""지점 분리 — 본사→전체, 동광주첨단→첨단·동광주 (§62)

- 본사(HQ) 이름을 '전체'로 (전사 스코프 자리, MASTER·ADMIN 소속. type 은 HQ 유지).
- 동광주첨단(BRANCH)을 첨단·동광주 둘로 분리. 인원 0 전제 —
  자동시드 env_items(재시드 가능)만 달려 있어 정리 후 새 지점에서 다시 시드된다.
  혹시 인원이 있으면 데이터 보호를 위해 중단한다.

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-08-03 09:30:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b0c1d2e3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1) 본사(HQ) → '전체'
    conn.execute(sa.text("UPDATE branches SET name = '전체' WHERE type = 'HQ'"))

    # 2) 동광주첨단 정리 (인원 0 전제 — 아니면 중단)
    row = conn.execute(sa.text("SELECT id FROM branches WHERE name = '동광주첨단'")).fetchone()
    if row is not None:
        dg = row[0]
        emp = conn.execute(
            sa.text("SELECT count(*) FROM employees WHERE branch_id = :b"), {"b": dg}
        ).scalar()
        if emp:
            raise RuntimeError(
                f"동광주첨단에 직원 {emp}명이 있어 자동 분리를 중단합니다. "
                "인원을 첨단/동광주로 옮긴 뒤 다시 실행하세요."
            )
        # 재시드 가능한 자동 env_items 만 있음 → 정리 후 지점 삭제
        conn.execute(sa.text("DELETE FROM env_task_logs WHERE branch_id = :b"), {"b": dg})
        conn.execute(sa.text("DELETE FROM env_items WHERE branch_id = :b"), {"b": dg})
        conn.execute(sa.text("DELETE FROM branches WHERE id = :b"), {"b": dg})

    # 3) 첨단·동광주 생성 (중복 방지). id 는 파이썬에서 생성(varchar 컬럼과 타입 일치).
    for name in ("첨단", "동광주"):
        exists = conn.execute(
            sa.text("SELECT 1 FROM branches WHERE name = :n"), {"n": name}
        ).fetchone()
        if exists is None:
            conn.execute(
                sa.text("INSERT INTO branches (id, name, type) VALUES (:id, :n, :t)"),
                {"id": str(uuid.uuid4()), "n": name, "t": "BRANCH"},
            )


def downgrade() -> None:
    # 지점 분리는 되돌리지 않는다(재병합 시 기록 귀속이 모호) — no-op
    pass
