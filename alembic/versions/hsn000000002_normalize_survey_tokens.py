"""설문 토큰 보완 — 토큰이 없는 지점에만 공개 토큰 발급

초기 설문 토큰은 token_urlsafe(12)로 만들어 길이와 문자가 달랐다.
기존 QR을 운영 중 무효화하면 안 되므로 이미 발급된 토큰은 보존한다.
현재 공개 주소 정책인 public_token()은 토큰이 없는 지점에만 사용한다.

Revision ID: hsn000000002
Revises: hsn000000001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.tokens import public_token

revision: str = "hsn000000002"
down_revision: Union[str, Sequence[str], None] = "hsn000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id FROM branches "
            "WHERE type = 'BRANCH' AND survey_token IS NULL"
        )
    ).fetchall()
    tokens = {
        token
        for (token,) in conn.execute(
            sa.text("SELECT survey_token FROM branches WHERE survey_token IS NOT NULL")
        ).fetchall()
    }
    for (branch_id,) in rows:
        token = public_token()
        while token in tokens:
            token = public_token()
        tokens.add(token)
        conn.execute(
            sa.text("UPDATE branches SET survey_token = :token WHERE id = :id"),
            {"token": token, "id": branch_id},
        )


def downgrade() -> None:
    # 기존 토큰을 보존하므로 되돌릴 때도 이미 발급된 QR을 건드리지 않는다.
    pass
