"""다짐(Dagym) 지점 키 — branches.dajim_gym_id

출석 이력을 브로제이만이 아니라 **다짐에서도** 받는다 (2026-08-26).

    화순      브로제이(BroJ)  — REST, 그룹이 하나뿐이라 키가 설정에 있다
    첨단      다짐(Dagym)     — GraphQL, 지점마다 gym_id 가 다르다
    동광주    다짐(Dagym)

**지점마다 값이 다르니 설정이 아니라 지점 행에 둔다.** 설정에 넣으면
`DAJIM_GYM_ID_첨단` 같은 이름이 지점 수만큼 늘고, 지점을 하나 더 열 때마다
배포를 해야 한다. v1(`HiFIS-Server`)도 같은 이유로 `Branch.dajim_gym_id` 였다.

브로제이 키는 설정에 그대로 둔다 — **그룹이 하나뿐이라** 지점별로 나눌 것이 없다.

값은 마이그레이션에서 심지 않는다. 다짐 관리자에서 지점을 열 때 받는 값이라
`PATCH /branches/{id}` 로 넣는다 (지금 두 지점 값은 대표가 갖고 있다).

Revision ID: djm000000001
Revises: brj000000001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "djm000000001"
down_revision: Union[str, Sequence[str], None] = "brj000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("dajim_gym_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("branches", "dajim_gym_id")
