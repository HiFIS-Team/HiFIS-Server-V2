"""사내톡 — 답글·시스템 메시지·전송 취소 (앱 목업 대응)

앱 채팅 화면이 이미 갖고 있던 것들을 서버가 받쳐 준다.
  - reply_to_id : 말풍선 위 인용 (답글)
  - kind        : TEXT / SYSTEM (초대·나가기·이름 변경 안내는 가운데 회색 한 줄)
  - deleted_at  : 전송 취소 (행은 남기고 목록에서만 뺀다 — 답글이 가리키던 원문 보존)

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-08-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'chat_messages',
        sa.Column(
            'kind',
            sa.String(length=16),
            nullable=False,
            server_default='TEXT',
        ),
    )
    op.add_column(
        'chat_messages',
        sa.Column('reply_to_id', sa.String(length=36), nullable=True),
    )
    op.add_column(
        'chat_messages',
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_chat_messages_reply_to_id',
        'chat_messages',
        'chat_messages',
        ['reply_to_id'],
        ['id'],
    )
    # 목록 조회가 늘 살아 있는 메시지만 최신순으로 훑는다
    op.create_index(
        'ix_chat_messages_room_alive',
        'chat_messages',
        ['room_id', 'created_at'],
        postgresql_where=sa.text('deleted_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_chat_messages_room_alive', table_name='chat_messages')
    op.drop_constraint('fk_chat_messages_reply_to_id', 'chat_messages', type_='foreignkey')
    op.drop_column('chat_messages', 'deleted_at')
    op.drop_column('chat_messages', 'reply_to_id')
    op.drop_column('chat_messages', 'kind')
