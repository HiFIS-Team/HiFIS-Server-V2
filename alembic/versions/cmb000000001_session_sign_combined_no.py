"""세션 싸인에 합친 회차 번호

Revision ID: cmb000000001
Revises: bdm000000001
Create Date: 2026-09-27

미리 재등록한 회원은 앱이 남은 등록권을 **합쳐** 보여준다 (8회 남음 + 10회
재등록 → `12/30회차`). 싸인은 여전히 등록권 단위로 차감되고 `session_no` 도
등록권마다 1 부터 다시 센다 — PT 설문·운동일지가 그 번호를 본다.

그래서 **싸인할 때 화면에 보인 번호를 따로 남긴다.** 기록 목록이 이걸 그대로
보여준다. 지나간 기록은 그때 어떤 등록권이 겹쳐 있었는지 알 수 없어서
**채우지 않는다** — null 이면 앱이 예전처럼 `session_no/total` 로 그린다.
"""

import sqlalchemy as sa
from alembic import op

revision = "cmb000000001"
down_revision = "bdm000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("session_signs", sa.Column("combined_no", sa.Integer(), nullable=True))
    op.add_column("session_signs", sa.Column("combined_total", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("session_signs", "combined_total")
    op.drop_column("session_signs", "combined_no")
