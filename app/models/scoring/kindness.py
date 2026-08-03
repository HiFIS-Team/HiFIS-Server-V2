"""KindnessSurvey (회원 친절도 설문) 모델 — CLAUDE.md §4.5.

외부 QR 폼(네이버폼 등)에서 웹훅으로 수신. 칭찬 직원에게 KINDNESS +10.
"""

from datetime import datetime

from sqlalchemy import Boolean, SmallInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


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

    # 별점 1~5 — **선택**이다. 앱 랭킹의 '리뷰 27건 · ★4.5' 가 이 값을 쓴다.
    # 안 받은 설문은 null 이고 평균에서 빠진다.
    stars: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
