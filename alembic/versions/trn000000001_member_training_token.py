"""회원 공개 수업 주소 토큰 + 일지 작성자 nullable

회원이 `hifis.app/training/{token}` 으로 자기 운동 기록을 본다.
그 화면에서 개인 운동을 직접 적을 수 있어서 `workout_logs.author_id` 가
비어 있을 수 있게 된다 (직원이 아니라 회원이 쓴 줄).

Revision ID: trn000000001
Revises: wko000000001
Create Date: 2026-08-30
"""

import secrets

import sqlalchemy as sa
from alembic import op

revision = "trn000000001"
down_revision = "wko000000001"
branch_labels = None
depends_on = None

#: `app/core/tokens.py` 와 같은 알파벳 — 헷갈리는 글자(0·o·1·l·i)가 없다
_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
_LENGTH = 12


def _token() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))


def upgrade() -> None:
    op.add_column("members", sa.Column("training_token", sa.String(length=24), nullable=True))

    # 이미 있는 회원에게도 주소를 하나씩 준다 — 없으면 웹이 아예 안 열린다
    bind = op.get_bind()
    ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM members"))]
    used: set[str] = set()
    for member_id in ids:
        token = _token()
        while token in used:
            token = _token()
        used.add(token)
        bind.execute(
            sa.text("UPDATE members SET training_token = :t WHERE id = :i"),
            {"t": token, "i": member_id},
        )

    op.create_index("ix_members_training_token", "members", ["training_token"], unique=True)

    op.alter_column("workout_logs", "author_id", existing_type=sa.String(length=36), nullable=True)


def downgrade() -> None:
    op.alter_column("workout_logs", "author_id", existing_type=sa.String(length=36), nullable=False)
    op.drop_index("ix_members_training_token", table_name="members")
    op.drop_column("members", "training_token")
