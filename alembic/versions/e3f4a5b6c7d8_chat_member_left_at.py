"""사내톡 — 나간 방 이력 (chat_room_members.left_at)

방을 나갈 때 멤버십 행을 지우지 않고 시각만 찍는다.
'최근 나간 항목'에서 다시 찾아볼 수 있어야 하고, 지우면 언제 나갔는지가 사라진다.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-08-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'chat_room_members',
        sa.Column('left_at', sa.DateTime(timezone=True), nullable=True),
    )
    # 활성 멤버 조회가 늘 left_at IS NULL 로 걸린다
    op.create_index(
        'ix_chat_room_members_active',
        'chat_room_members',
        ['room_id', 'employee_id'],
        postgresql_where=sa.text('left_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_chat_room_members_active', table_name='chat_room_members')
    op.drop_column('chat_room_members', 'left_at')
