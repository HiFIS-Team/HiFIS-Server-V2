"""사내톡 모델 — ChatRoom · ChatRoomMember · Message (CLAUDE.md §6.11, §9.3).

- 멤버십은 조인 테이블(ChatRoomMember)로 — last_read_at 로 안읽음 수 계산.
- 메시지 반응은 공통 Reaction(targetType=MESSAGE) 재사용 (§6.12).
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


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


class Message(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "chat_messages"

    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_rooms.id"), nullable=False, index=True
    )
    sender_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
