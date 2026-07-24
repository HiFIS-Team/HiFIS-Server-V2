"""Project (프로젝트) 모델 — CLAUDE.md §6.1.

status(대기/진행중/완료/누락)는 progress+due 파생 → 저장 안 함, 응답 시 계산.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    steps: Mapped[str] = mapped_column(Text, nullable=False, default="")
    due: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assignee_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    extension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 누락(마감 초과) 알림을 보낸 시각 — 1회만 보내기 위한 멱등 표시. 마감(due) 변경 시 초기화.
    overdue_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
