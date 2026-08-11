"""회원 방문 경로 (members.visit_path)

블로그·인스타·OT→PT 로 온 회원을 등록하면 담당 트레이너에게 5점이 붙는다.
워크인·지인소개는 점수가 없다.

**백필하지 않는다.** 이 칸이 생기기 전에 등록된 회원은 어떻게 왔는지 아무도
모른다 — 아무 값이나 넣으면 그게 사실처럼 남는다. null 로 둔다.

Revision ID: vis000000001
Revises: inv000000001
"""

from alembic import op
import sqlalchemy as sa

revision = "vis000000001"
down_revision = "inv000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "members",
        sa.Column(
            "visit_path",
            sa.Enum(
                "WALK_IN",
                "REFERRAL",
                "BLOG",
                "INSTAGRAM",
                "OT_TO_PT",
                name="visitpath",
                native_enum=False,
                length=20,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("members", "visit_path")
