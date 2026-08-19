"""프로젝트 댓글을 comments 로 옮긴다 (2026-08-19)

예전에는 `project_activities` 에 **시스템 활동과 한 타임라인**으로 섞여 있었다
(`kind='COMMENT'`). 프로젝트 상세도 공지·회의록과 같은 모양(오른쪽 하트·댓글
세로 줄 + 댓글 시트)이 되면서 저장도 한곳으로 모은다.

옮기고 나면 `project_activities` 는 **순수 활동 기록**만 남는다 —
'무슨 일이 있었나' 를 훑는 자리와 '무슨 말을 했나' 가 갈린다.

Revision ID: pcmt00000001
Revises: cmt000000001
"""

from alembic import op

revision = "pcmt00000001"
down_revision = "cmt000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 작성자가 없는 줄(시스템)은 댓글일 수 없다 — 안전하게 걸러 둔다
    op.execute(
        """
        INSERT INTO comments (id, target_type, target_id, author_id, body, created_at, updated_at)
        SELECT id, 'PROJECT', project_id, actor_id, COALESCE(body, ''), created_at, updated_at
          FROM project_activities
         WHERE kind = 'COMMENT' AND actor_id IS NOT NULL
        """
    )
    op.execute("DELETE FROM project_activities WHERE kind = 'COMMENT'")


def downgrade() -> None:
    op.execute(
        """
        INSERT INTO project_activities (id, project_id, actor_id, kind, body, created_at, updated_at)
        SELECT id, target_id, author_id, 'COMMENT', body, created_at, updated_at
          FROM comments
         WHERE target_type = 'PROJECT'
        """
    )
    op.execute("DELETE FROM comments WHERE target_type = 'PROJECT'")
