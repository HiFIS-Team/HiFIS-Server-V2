"""Member (회원/고객) 모델 — CLAUDE.md §3.1."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Member(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "members"

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=False, index=True
    )
    # 담당 트레이너 — 매출 인센 귀속 (§3.1)
    owner_trainer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    referrer_member_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("members.id"), nullable=True
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
