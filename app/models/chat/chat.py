"""사내톡 모델 — ChatRoom · ChatRoomMember · Message (CLAUDE.md §6.11, §9.3).

- 멤버십은 조인 테이블(ChatRoomMember)로 — last_read_at 로 안읽음 수 계산.
- 메시지 반응은 공통 Reaction(targetType=MESSAGE) 재사용 (§6.12).
- 전송 취소는 **소프트 삭제** — 목록에서 빼되 행은 남긴다.
  답글이 가리키던 원문이 통째로 사라지면 그 답글이 뜻을 잃는다.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.enums import MessageKind


class ChatRoom(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "chat_rooms"

    name: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 그룹방 이름(DM 은 null)
    is_group: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), nullable=False)


class ChatRoomMember(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "chat_room_members"
    __table_args__ = (UniqueConstraint("room_id", "employee_id", name="uq_chat_member"),)

    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_rooms.id"), nullable=False, index=True
    )
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 나간 시각 — 행을 지우지 않고 남긴다. '최근 나간 항목'에서 다시 찾을 수 있어야
    # 하고, 지워 버리면 언제 나갔는지가 사라진다. null 이면 지금 방에 있는 것.
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 이 방 알림 끄기 — **사람마다 따로다.** 켜 둔 사람에게는 그대로 간다.
    # 꺼도 대화는 그대로 오고 안읽음도 센다. 푸시만 안 보낸다.
    muted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class Message(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "chat_messages"

    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_rooms.id"), nullable=False, index=True
    )
    sender_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # 서버가 남긴 안내(초대·나가기·이름 변경)는 SYSTEM — 보낸 사람은 그 일을 한 사람이다
    kind: Mapped[MessageKind] = mapped_column(
        Enum(MessageKind, native_enum=False, length=16),
        nullable=False,
        default=MessageKind.TEXT,
        server_default=MessageKind.TEXT.value,
    )

    # 답글 대상 — 원문이 지워져도 링크는 남긴다(앱이 '삭제된 메시지'로 그린다)
    reply_to_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chat_messages.id"), nullable=True
    )
