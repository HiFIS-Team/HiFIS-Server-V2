"""NoticeRead (공지 읽음) 모델 — CLAUDE.md §6.4.

(공지·직원)당 최대 1행. 존재하면 '읽음', 없으면 '안 읽음'. 읽음 처리는 멱등(중복 방지 유니크).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class NoticeRead(UUIDMixin, Base):
    __tablename__ = "notice_reads"
    __table_args__ = (UniqueConstraint("notice_id", "employee_id", name="uq_notice_read"),)

    notice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("notices.id"), nullable=False, index=True
    )
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
