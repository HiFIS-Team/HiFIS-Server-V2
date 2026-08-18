"""계정 정지 — employees.suspended_at · suspend_reason

이용약관 제8조 1항(위반 시 이용 제한)을 실제로 집행하는 자리다 (2026-08-19).

**재직 상태(`status`)와 다른 축으로 둔다.** `RESIGNED`·`INACTIVE` 로 밀면
조직도·근태 판정·인원수에서 통째로 사라진다 — 그건 정지가 아니라 퇴사다.
정지된 사람도 여전히 재직 중이다. 고용 형태를 재직 상태와 갈라 둔 것과
같은 판단이다 (backend-gap 75).

`suspend_reason` 은 **로그인 화면에 그대로 뜨는 글**이다. 무엇을 어겼고
풀려면 무엇을 해야 하는지를 여기 적는다 — 왜 막혔는지 모르면 본인은 고장으로
읽고, 풀 방법도 알 수 없다.

정지할 때 `token_version` 을 올려 켜 둔 앱의 세션까지 끊는다 (컬럼은 이미 있다).

Revision ID: sus000000001
Revises: trl000000001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sus000000001"
down_revision: Union[str, None] = "trl000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employees", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("employees", sa.Column("suspend_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "suspend_reason")
    op.drop_column("employees", "suspended_at")
