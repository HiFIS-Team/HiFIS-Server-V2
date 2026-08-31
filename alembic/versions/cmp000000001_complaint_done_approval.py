"""컴플레인 해결 완료에 대표 승인을 끼운다

해결 완료를 찍으면 찍은 사람에게 환경정비 '클레임해결' 점수가 붙는데,
지금까지 **아무나 찍을 수 있었다.** MANAGER·MEMBER 가 누르면 승인 대기로
가고 MASTER 가 승인해야 완료가 된다 (점수는 올린 사람에게 간다).

`improvement_status` 는 VARCHAR 라(`native_enum=False`) 값이 하나 늘어도
타입을 손댈 것이 없다 — 컬럼 둘만 더한다.

Revision ID: cmp000000001
Revises: trn000000001
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op

revision = "cmp000000001"
down_revision = "trn000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kindness_surveys",
        sa.Column("done_requested_by_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "kindness_surveys",
        sa.Column("done_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_kindness_surveys_done_requested_by",
        "kindness_surveys",
        "employees",
        ["done_requested_by_id"],
        ["id"],
    )


def downgrade() -> None:
    # 승인 대기로 서 있던 것은 되돌릴 때 해결중으로 내린다 — 값이 사라지면
    # enum 에 없는 글자가 남는다
    op.execute(
        "UPDATE kindness_surveys SET improvement_status = 'WORKING' "
        "WHERE improvement_status = 'DONE_REQUESTED'"
    )
    op.drop_constraint(
        "fk_kindness_surveys_done_requested_by", "kindness_surveys", type_="foreignkey"
    )
    op.drop_column("kindness_surveys", "done_requested_at")
    op.drop_column("kindness_surveys", "done_requested_by_id")
