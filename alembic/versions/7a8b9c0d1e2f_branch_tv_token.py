"""매장 TV 토큰 — branches.tv_token

TV 가 여는 주소(`/tv/{tv_token}`)를 지점마다 하나씩 둔다.

**설문 토큰(`survey_token`)을 같이 쓰지 않는다.** 그건 설문을 *쓰는* 열쇠라
TV 주소창에 띄워 두면 앞을 지나는 누구나 가짜 칭찬을 넣을 수 있다.
TV 쪽은 읽기 전용이라 새어도 화면이 한 장 더 보이는 것뿐이다.

Revision ID: 7a8b9c0d1e2f
Revises: 6f7a8b9c0d1e
"""

import secrets

import sqlalchemy as sa
from alembic import op

revision = "7a8b9c0d1e2f"
down_revision = "6f7a8b9c0d1e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("tv_token", sa.String(32), nullable=True))
    op.create_index("ix_branches_tv_token", "branches", ["tv_token"], unique=True)

    conn = op.get_bind()
    for (branch_id,) in conn.execute(sa.text("SELECT id FROM branches")).fetchall():
        conn.execute(
            sa.text("UPDATE branches SET tv_token = :t WHERE id = :i"),
            {"t": secrets.token_urlsafe(12), "i": branch_id},
        )


def downgrade() -> None:
    op.drop_index("ix_branches_tv_token", table_name="branches")
    op.drop_column("branches", "tv_token")
