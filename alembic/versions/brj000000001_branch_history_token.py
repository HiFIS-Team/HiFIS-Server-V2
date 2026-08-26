"""출석 이력 주소 — branches.history_token

브로제이(BroJ)에 쌓인 회원 출입 기록을 달 단위로 집계해 보는 화면의 열쇠다
(`/history/{history_token}`).

**설문·TV 토큰과 따로 둔다.** 셋의 성격이 다르다.

    survey_token   회원이 글을 **쓰는** 열쇠 — 새면 가짜 칭찬이 들어온다
    tv_token       매장 벽에 걸리는 **읽기** 열쇠 — 회원 이름이 안 나간다
    history_token  **회원 명단**이 나간다 — 이름·전화·출석일이 줄줄이 뜬다

그래서 TV 토큰을 같이 쓰면 안 된다. 매장 TV 주소를 아는 사람이 곧 회원
명단을 볼 수 있게 된다.

**화순점만 발급한다.** 브로제이를 쓰는 지점이 거기뿐이라, 다른 지점 토큰은
`settings.broj_branch_name` 가드에서 막힌다.

Revision ID: brj000000001
Revises: sct000000001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "brj000000001"
down_revision: Union[str, Sequence[str], None] = "sct000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("history_token", sa.String(32), nullable=True))
    op.create_index(
        "ix_branches_history_token", "branches", ["history_token"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_branches_history_token", table_name="branches")
    op.drop_column("branches", "history_token")
