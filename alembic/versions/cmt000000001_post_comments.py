"""공지·회의록 댓글 — comments (2026-08-19)

반응과 같은 다형 구조(`target_type` + `target_id`)다. 프로젝트 댓글은
`project_activities` 에 시스템 활동과 섞여 있어서 여기 못 얹는다.

Revision ID: cmt000000001
Revises: pdone0000001
"""

from alembic import op
import sqlalchemy as sa

revision = "cmt000000001"
down_revision = "pdone0000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # 한 글의 댓글을 시간순으로 긁는 것이 유일한 조회다 — 그 모양으로 건다
    op.create_index(
        "ix_comments_target", "comments", ["target_type", "target_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_comments_target", table_name="comments")
    op.drop_table("comments")
