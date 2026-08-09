"""초대키 고용 형태 — invite_keys.employment_type

알바를 뽑을 길이 없었다. 어느 키로 가입하든 `Employee.employment_type` 기본값
(정규직)으로 들어와서, 알바로 들어온 사람을 대표가 나중에 손으로 바꿔 줘야 했다.

키가 지점·직급·권한을 정해 주듯 고용 형태도 **초대 시점에** 정한다.
들어온 뒤 정규직으로 올리거나 퇴사시키는 건 `PATCH /employees/{id}`(MASTER) 쪽이다.

이미 발급된 키는 전부 **정규직**으로 채운다 — 그때는 알바라는 갈래가 없었으니
정규직으로 뽑은 것이 맞다.

Revision ID: inv000000001
Revises: term00000001
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "inv000000001"
down_revision: Union[str, Sequence[str], None] = "term00000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default 로 기존 행까지 한 번에 채운다 (따로 UPDATE 를 돌 필요가 없다)
    op.add_column(
        "invite_keys",
        sa.Column(
            "employment_type",
            sa.String(20),
            nullable=False,
            server_default="FULL_TIME",
        ),
    )


def downgrade() -> None:
    op.drop_column("invite_keys", "employment_type")
