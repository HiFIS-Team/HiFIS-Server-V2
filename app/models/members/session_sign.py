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
    #: 서명 이미지 (로컬 §9.2) — **싸인을 생략하고 기록하면 비어 있다**
    signature_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: 회원 싸인 없이 **누가** 이 회차를 채웠나 (2026-09-05 요청)
    #:
    #: 비어 있으면 회원이 직접 서명한 정상 기록이다. 채워져 있으면 그 사람이
    #: 싸인을 못 받고 회차만 올린 것이라, 나중에 되짚을 이름이 남아야 한다.
    #: **불리언을 따로 안 둔다** — 둘로 나누면 '생략인데 누군지 모름' 같은
    #: 어긋난 줄이 생긴다. 여기 이름이 있으면 곧 생략이다.
    signature_skipped_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True, index=True
    )
