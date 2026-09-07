"""세션 싸인 — 회원 싸인 없이 회차를 채운 기록

Revision ID: sgs000000001
Revises: djm000000001
Create Date: 2026-09-05

회원이 자리에 없거나 서명을 못 받는 자리가 있어 **싸인을 생략하고 회차만**
올릴 수 있게 열었다. 그래서 둘이 바뀐다.

- `signature_url` 이 **비어도 된다** (생략하면 이미지가 아예 없다)
- `signature_skipped_by_id` 에 **누가 생략했는지**를 남긴다

불리언을 따로 안 둔다 — 이 칸이 차 있으면 곧 생략이다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sgs000000001"
down_revision: Union[str, Sequence[str], None] = "djm000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "session_signs", "signature_url", existing_type=sa.String(500), nullable=True
    )
    op.add_column(
        "session_signs",
        sa.Column("signature_skipped_by_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_session_signs_signature_skipped_by",
        "session_signs",
        "employees",
        ["signature_skipped_by_id"],
        ["id"],
    )
    op.create_index(
        "ix_session_signs_signature_skipped_by_id",
        "session_signs",
        ["signature_skipped_by_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_signs_signature_skipped_by_id", table_name="session_signs")
    op.drop_constraint(
        "fk_session_signs_signature_skipped_by", "session_signs", type_="foreignkey"
    )
    op.drop_column("session_signs", "signature_skipped_by_id")
    # 비어 있는 줄이 남아 있으면 NOT NULL 로 못 돌아간다 — 그 줄만 걷어 낸다
    op.execute("DELETE FROM session_signs WHERE signature_url IS NULL")
    op.alter_column(
        "session_signs", "signature_url", existing_type=sa.String(500), nullable=False
    )
