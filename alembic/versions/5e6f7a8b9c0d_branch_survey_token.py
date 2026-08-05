"""지점 설문 QR 토큰 — branches.survey_token

회원이 매장에서 QR 을 찍으면 `/survey/{survey_token}` 으로 온다.
지점 id 를 그대로 쓰지 않는 이유는 모델 주석에 적어 뒀다 (새면 갈아 끼워야 한다).

기존 지점에도 다 발급한다 — 나중에 지점이 늘면 그때는 생성 시점에 넣는다.

Revision ID: 5e6f7a8b9c0d
Revises: 4d5e6f7a8b9c
"""

import secrets

import sqlalchemy as sa
from alembic import op

revision = "5e6f7a8b9c0d"
down_revision = "4d5e6f7a8b9c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("survey_token", sa.String(32), nullable=True))
    op.create_index("ix_branches_survey_token", "branches", ["survey_token"], unique=True)

    # 이미 있는 지점에 하나씩 발급한다. 한 줄씩 도는 건 지점이 몇 개뿐이라서다
    conn = op.get_bind()
    for (branch_id,) in conn.execute(sa.text("SELECT id FROM branches")).fetchall():
        conn.execute(
            sa.text("UPDATE branches SET survey_token = :t WHERE id = :i"),
            {"t": secrets.token_urlsafe(12), "i": branch_id},
        )


def downgrade() -> None:
    op.drop_index("ix_branches_survey_token", table_name="branches")
    op.drop_column("branches", "survey_token")
