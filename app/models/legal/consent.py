"""동의 이력 모델 — 직원 약관(§12) · 회원 개인정보 수집(§13).

입증 책임이 회사에 있어 기록이 없으면 '안 받은 것'. 그래서 동의마다 시각·문서버전을 남긴다.
- EmployeeConsent: 직원 본인이 약관/개인정보에 동의(앱 온보딩).
- MemberConsent: 센터 회원(정보주체=손님) 개인정보 수집 동의 + 서명 이미지(로컬 저장 §9.2).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class EmployeeConsent(UUIDMixin, Base):
    __tablename__ = "employee_consents"

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    doc_type: Mapped[str] = mapped_column(String(40), nullable=False)     # "TERMS" / "PRIVACY" 등
    doc_version: Mapped[str] = mapped_column(String(40), nullable=False)  # 동의한 문서 버전
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)     # 감사 보조(선택)
    agreed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemberConsent(UUIDMixin, Base):
    __tablename__ = "member_consents"

    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("members.id"), nullable=False, index=True
    )
    doc_type: Mapped[str] = mapped_column(String(40), nullable=False)     # 기본 "PRIVACY"
    doc_version: Mapped[str] = mapped_column(String(40), nullable=False)
    signature_url: Mapped[str] = mapped_column(String(500), nullable=False)  # 서명 이미지 경로
    # 동의를 받은 직원(입증 보조) — 손님 대신 기록한 주체
    collected_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
    agreed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
