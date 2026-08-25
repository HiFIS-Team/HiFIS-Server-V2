"""설문 토큰 형식 통일 — 모든 지점을 8자 공개 토큰으로 정규화

초기 설문 토큰은 token_urlsafe(12)로 만들어 길이와 문자가 달랐다.
현재 공개 주소 정책인 public_token()으로 모든 BRANCH 토큰을 다시 발급한다.
기존 QR은 폐기되므로 새 토큰 기준으로 QR을 다시 뽑아야 한다.

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
        sa.text("SELECT id FROM branches WHERE type = 'BRANCH'")
    ).fetchall()
    tokens: set[str] = set()
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
    raise RuntimeError("설문 토큰은 이전 값으로 복원할 수 없습니다")
