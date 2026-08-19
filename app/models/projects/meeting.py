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

    #: 어느 지점의 회의록인가 — 프로젝트와 **같은 규칙**이다 (2026-08-19).
    #: 만들 때 작성자의 지점을 찍고, 같은 `Branch.share_group` 끼리만 본다.
    #: `NULL` 은 전 지점 (본사가 쓴 것과 이 컬럼이 생기기 전 것).
    branch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=True, index=True
    )
