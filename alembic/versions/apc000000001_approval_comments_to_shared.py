"""결재 댓글을 공용 댓글 표로 옮긴다 (2026-08-31).

결재 댓글은 `approvals.comments` JSONB 였다 — **줄마다 id 가 없어서** 고치고
지울 수가 없었고, 그래서 결재만 댓글 창이 다른 화면을 쓰고 있었다.
공지·회의록·프로젝트와 같은 창을 쓰려면 같은 표에 있어야 한다.

**JSONB 는 안 지운다.** 이미 나간 앱이 `ApprovalOut.comments` 를 읽고 있어서,
지우면 그 빌드에서 옛 댓글이 통째로 사라진다. 새 앱은 `comments` 표만 본다.

Revision ID: apc000000001
Revises: mtf000000001
"""

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "apc000000001"
down_revision = "mtf000000001"
branch_labels = None
depends_on = None


def _when(value) -> datetime:
    """JSONB 에 글자로 든 시각 → datetime. 못 읽으면 지금으로 둔다."""
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, comments FROM approvals WHERE jsonb_array_length(COALESCE(comments,'[]'::jsonb)) > 0")
    ).all()
    moved = 0
    for approval_id, comments in rows:
        for c in comments or []:
            author = c.get("author_id")
            body = (c.get("body") or "").strip()
            if not author or not body:
                continue
            conn.execute(
                sa.text(
                    "INSERT INTO comments (id, target_type, target_id, author_id, body,"
                    " created_at, updated_at)"
                    " VALUES (:id, 'APPROVAL', :tid, :aid, :body, :made, :made)"
                ),
                {
                    "id": uuid.uuid4().hex,
                    "tid": approval_id,
                    "aid": author,
                    "body": body,
                    # 옛 줄은 만든 시각만 있다 — 고친 적이 없으니 둘을 같게 둔다.
                    # JSONB 라 글자로 들어 있어서 되돌려 놔야 한다
                    "made": _when(c.get("created_at")),
                },
            )
            moved += 1
    print(f"[apc000000001] 결재 댓글 {moved}건을 공용 표로 옮겼다")


def downgrade() -> None:
    # 옮겨 온 줄만 걷는다 — JSONB 원본은 그대로 있어서 되돌려도 안 잃는다
    op.execute("DELETE FROM comments WHERE target_type = 'APPROVAL'")
