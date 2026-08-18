"""환경정비 수행 기록에 사진·위치 추가

대표 요청 (2026-08-18). 현수막은 걸었다고 칩만 누르면 실제로 걸었는지 확인할
방법이 없어서, **사진과 어디에 걸었는지를 같이 받는다.**

**컬럼은 nullable 이다.** 이미 쌓인 기록에는 값이 없고, 어느 항목이 필수인지는
라우터의 `PHOTO_REQUIRED_ITEMS` 가 정한다 — 나중에 족자·전단지를 더하거나 뺄 때
DB 를 안 건드리려는 것이다.

Revision ID: env000000005
Revises: env000000004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "env000000005"
down_revision: Union[str, Sequence[str], None] = "env000000004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("env_task_logs", sa.Column("photo_url", sa.String(length=255), nullable=True))
    op.add_column("env_task_logs", sa.Column("place", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("env_task_logs", "place")
    op.drop_column("env_task_logs", "photo_url")
