"""추첨 게임 영상 — 만들어 둔 mp4 의 자리

매월 1일에 도는 잡(`workers/draw_videos.py`)이 게임 화면을 찍어 mp4 로 굽고
그 경로를 여기 적는다. 앱이 그걸 내려받아 사진 앱에 저장한다.

**경로만 담는다.** 파일은 다른 첨부와 같이 `uploads/` 에 놓인다 —
DB 에 넣으면 한 건에 10MB 라 백업이 통째로 무거워진다.

Revision ID: drw000000003
Revises: drw000000002
"""

import sqlalchemy as sa
from alembic import op

revision = "drw000000003"
down_revision = "drw000000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("draws", sa.Column("video_path", sa.String(length=500), nullable=True))
    op.add_column("draws", sa.Column("video_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("draws", "video_at")
    op.drop_column("draws", "video_path")
