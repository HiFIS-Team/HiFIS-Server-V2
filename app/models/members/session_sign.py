"""SessionSign (세션 싸인 = 세션지) 모델 — CLAUDE.md §3.3.

기록의 주인은 트레이너, 회원 서명은 수행 증명. 담당(Member.ownerTrainerId) vs
수행(performedByTrainerId) 분리 — 대타면 다름. 수행 = 수업 개수(CLASS) 점수.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class SessionSign(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "session_signs"

    registration_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("registrations.id"), nullable=False, index=True
    )
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("members.id"), nullable=False, index=True
    )
    performed_by_trainer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    session_no: Mapped[int] = mapped_column(Integer, nullable=False)  # n회차
    signature_url: Mapped[str] = mapped_column(String(500), nullable=False)  # 서명 이미지 (로컬 §9.2)
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
