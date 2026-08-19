"""프로젝트 완료를 진행률에서 떼어낸다 — projects.completed_at

예전에는 **진행률 100% 가 곧 완료**였다. 마지막 할 일에 체크하는 순간 프로젝트가
완료되고 담당자에게 점수가 붙어서, **잘못 누르면 되돌릴 방법이 대표뿐**이었다
(2026-08-19 대표 요청).

이제 체크를 다 해도 완료가 아니다. 담당자가 `POST /projects/{id}/complete` 를
눌러야 완료다. 앱은 그때 '완료 후 되돌릴 수 없어요' 를 한 번 묻는다.

**이미 100% 인 프로젝트는 완료로 백필한다** — 그 상태로 점수까지 정산이 끝나
있어서, 안 채우면 완료된 프로젝트가 통째로 진행 중으로 돌아간다.
채우는 시각은 완료 정산을 남긴 `completed_notified_at`, 없으면 `updated_at`.

Revision ID: pdone0000001
Revises: bgrp00000001
"""

from alembic import op
import sqlalchemy as sa

revision = "pdone0000001"
down_revision = "bgrp00000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        UPDATE projects
           SET completed_at = COALESCE(completed_notified_at, updated_at)
         WHERE progress >= 100
        """
    )


def downgrade() -> None:
    op.drop_column("projects", "completed_at")
