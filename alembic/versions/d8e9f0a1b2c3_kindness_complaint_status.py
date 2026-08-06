"""친절 설문 컴플레인 처리 단계 (kindness_surveys)

설문의 '개선했으면 하는 부분' 이 곧 컴플레인이다. 해결하면 DONE 이 되고
매장 TV 화면이 그것만 골라 '해결 완료' 로 띄운다.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-08-04 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'kindness_surveys',
        sa.Column(
            'improvement_status',
            sa.String(length=16),
            nullable=False,
            server_default='PENDING',
        ),
    )
    op.add_column(
        'kindness_surveys',
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'kindness_surveys',
        sa.Column('resolved_by_id', sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        'fk_kindness_surveys_resolved_by',
        'kindness_surveys',
        'employees',
        ['resolved_by_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_kindness_surveys_resolved_by', 'kindness_surveys', type_='foreignkey'
    )
    op.drop_column('kindness_surveys', 'resolved_by_id')
    op.drop_column('kindness_surveys', 'resolved_at')
    op.drop_column('kindness_surveys', 'improvement_status')
