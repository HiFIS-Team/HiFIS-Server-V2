"""Meeting (회의록) 모델 — CLAUDE.md §6.3. blocks 는 리치 콘텐츠 블록 배열."""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import MeetingScope


class Meeting(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "meetings"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    blocks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    scope: Mapped[MeetingScope] = mapped_column(
        SAEnum(MeetingScope, native_enum=False, length=20), nullable=False
    )
    attendee_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=True
    )
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), nullable=False)
    meeting_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
