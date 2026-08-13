"""employees.first_login_at — 처음 로그인한 시각

프로필 상세가 '가입일'과 나란히 보여준다 (2026-08-13 결정).
가입만 하고 아직 안 들어온 사람을 가리는 값이다.

**이미 있는 직원은 접속 기록에서 백필한다.** `access_logs` 의 로그인 성공 중
제일 오래된 것이 곧 첫 접속이다. 다만 그 기록은 **90일 뒤 파기**되므로,
그보다 오래 전에 들어온 사람은 채울 수 없어 null 로 남는다 (화면에서는 빈칸).

Revision ID: fst000000001
Revises: prj000000001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fst000000001"
down_revision: Union[str, Sequence[str], None] = "prj000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("first_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 남아 있는 접속 기록으로 채운다 — 로그인 성공 중 제일 이른 것
    op.execute(
        """
        UPDATE employees e
           SET first_login_at = s.at
        FROM (
            SELECT employee_id, MIN(created_at) AS at
            FROM access_logs
            WHERE event = 'LOGIN_SUCCESS' AND employee_id IS NOT NULL
            GROUP BY employee_id
        ) s
        WHERE s.employee_id = e.id
        """
    )


def downgrade() -> None:
    op.drop_column("employees", "first_login_at")
