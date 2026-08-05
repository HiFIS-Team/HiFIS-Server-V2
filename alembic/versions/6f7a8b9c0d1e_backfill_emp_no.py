"""사번 없는 옛 직원에게 사번 발급 — employees.emp_no 백필

사번은 가입·직원 추가·시드에서 `unique_emp_no` 로 이미 다 발급된다.
그런데 그 로직이 붙기 전(2026-07-24)에 만들어진 5명만 비어 있었다.

**출퇴근 바코드가 이 값이라, 비어 있으면 그 사람은 스캔 자체를 못 한다.**
앱에 '사번 없음' 화면을 만드는 것보다 값을 채우는 게 맞다.

`unique_emp_no` 와 같은 규칙({입사연도}-{4자리 순번})으로, 그 사람의
**입사 연도**를 써서 붙인다 (지금 연도가 아니다 — 사번은 입사 시점을 뜻한다).

Revision ID: 6f7a8b9c0d1e
Revises: 5e6f7a8b9c0d
"""

import sqlalchemy as sa
from alembic import op

revision = "6f7a8b9c0d1e"
down_revision = "5e6f7a8b9c0d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT id, EXTRACT(YEAR FROM joined_at)::int AS yr FROM employees "
            "WHERE emp_no IS NULL AND deleted_at IS NULL ORDER BY joined_at, id"
        )
    ).fetchall()

    for employee_id, year in rows:
        prefix = f"{year}-"
        # 그 연도의 마지막 순번 다음 — 한 명씩 넣으면서 매번 다시 본다
        last = conn.execute(
            sa.text(
                "SELECT emp_no FROM employees WHERE emp_no LIKE :p "
                "ORDER BY emp_no DESC LIMIT 1"
            ),
            {"p": f"{prefix}%"},
        ).scalar()
        seq = int(last.split("-")[1]) + 1 if last else 1
        conn.execute(
            sa.text("UPDATE employees SET emp_no = :n WHERE id = :i"),
            {"n": f"{prefix}{seq:04d}", "i": employee_id},
        )


def downgrade() -> None:
    # 되돌리지 않는다 — 어느 사번이 이 백필로 생긴 것인지 구분할 방법이 없고,
    # 사번은 한 번 나가면 바코드로 찍혀 돌아다니는 값이라 지우면 안 된다.
    pass
