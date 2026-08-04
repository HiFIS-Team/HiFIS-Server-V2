"""Event (일정) 모델 — CLAUDE.md §6.8."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import EventStatus


class Event(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "events"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 종일 일정
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False)
    place: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 장소
    attendee_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # 참석자
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), nullable=False)
    # 승인 상태 — MASTER·ADMIN 이 올린 것만 바로 APPROVED
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, name="eventstatus"),
        nullable=False,
        default=EventStatus.APPROVED,
        index=True,
    )
