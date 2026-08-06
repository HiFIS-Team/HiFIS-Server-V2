"""KindnessSurvey (회원 친절도 설문) 모델 — CLAUDE.md §4.5.

외부 QR 폼(네이버폼 등)에서 웹훅으로 수신. 칭찬 직원에게 KINDNESS +10.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import ComplaintStatus


class KindnessSurvey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "kindness_surveys"

    motivation: Mapped[str] = mapped_column(Text, nullable=False)  # ① 운동 시작 계기
    praised_employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )  # ② 칭찬 직원
    praise_comment: Mapped[str] = mapped_column(Text, nullable=False)
    improvement: Mapped[str | None] = mapped_column(Text, nullable=True)  # ③ 보완점
    member_name: Mapped[str] = mapped_column(String(50), nullable=False)  # ④
    member_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False)  # ⑤ 동의(필수)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 컴플레인 처리 — `improvement` 가 적힌 설문에서만 의미가 있다.
    # 비어 있는 설문도 PENDING 으로 두지만 앱이 컴플레인으로 세지 않는다.
    improvement_status: Mapped[ComplaintStatus] = mapped_column(
        SAEnum(ComplaintStatus, native_enum=False, length=16),
        nullable=False,
        default=ComplaintStatus.PENDING,
        server_default=ComplaintStatus.PENDING.value,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
