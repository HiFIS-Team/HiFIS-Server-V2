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
    # 결재한 시각(승인·반려 둘 다) — **올리자마자 APPROVED 가 된 것은 null 이다.**
    #
    # 결재 이력(GET /me/inbox?status=APPROVED)에서 '대표가 승인해 준 일정'과
    # '대표가 올려서 그냥 선 일정'을 가르는 유일한 단서다. status 만 보면
    # 전사 달력 일정이 통째로 결재 이력에 선다.
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 반려 사유 — 급여·월차·전자결재와 같은 칸이다.
    # 예전에는 알림 본문에만 실어 보내고 어디에도 안 남겼다.
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
