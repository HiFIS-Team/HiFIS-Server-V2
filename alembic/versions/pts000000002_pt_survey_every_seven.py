"""PT 만족도 폼을 7회차마다 — 등록권당 하나 제약을 푼다

Revision ID: pts000000002
Revises: cmb000000001
Create Date: 2026-09-27

예전에는 신규 등록권의 7회차 **한 번**이라 `registration_id` 가 유니크였다.
이제 회원 누적 7·14·21…회차마다 열어서 한 등록권에 여러 줄이 생긴다
(20회권이면 7·14 두 번). 중복은 앱 코드가 회원·회차로 막는다.
"""

from alembic import op

revision = "pts000000002"
down_revision = "cmb000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pt_surveys DROP CONSTRAINT IF EXISTS pt_surveys_registration_id_key")


def downgrade() -> None:
    op.create_unique_constraint(
        "pt_surveys_registration_id_key", "pt_surveys", ["registration_id"]
    )
