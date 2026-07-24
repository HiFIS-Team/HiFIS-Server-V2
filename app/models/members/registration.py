"""Registration (PT 등록 = 매출 + 세션권) 모델 — CLAUDE.md §3.2."""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import RegistrationStatus, RegistrationType


class Registration(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "registrations"

    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("members.id"), nullable=False, index=True
    )
    # 담당(매출 인센 대상) 트레이너 (§3.2)
    trainer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    type: Mapped[RegistrationType] = mapped_column(
        SAEnum(RegistrationType, native_enum=False, length=20), nullable=False
    )
    total_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    used_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_paid: Mapped[int] = mapped_column(Integer, nullable=False)  # 결제액(원) — 인센 산정 기준
    session_unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RegistrationStatus] = mapped_column(
        SAEnum(RegistrationStatus, native_enum=False, length=20),
        nullable=False,
        default=RegistrationStatus.ACTIVE,
    )
    purchased_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
