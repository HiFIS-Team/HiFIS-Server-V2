"""Payslip (급여명세서) 모델 — CLAUDE.md §5.

대부분 계산 결과 스냅샷. 원천(Registration 매출, RankPolicy)에서 산출해 저장.
(employee_id, year_month) 유니크 — 재생성 시 교체.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import DeductionMethod, PayslipStatus, Rank


class Payslip(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "payslips"
    __table_args__ = (UniqueConstraint("employee_id", "year_month", name="uq_payslip"),)

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    year_month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # "2026-07"
    rank: Mapped[Rank] = mapped_column(SAEnum(Rank, native_enum=False, length=20), nullable=False)
    base_salary: Mapped[int] = mapped_column(Integer, nullable=False)
    incentive_new: Mapped[int] = mapped_column(Integer, nullable=False)
    incentive_renewal: Mapped[int] = mapped_column(Integer, nullable=False)
    other_allowances: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross: Mapped[int] = mapped_column(Integer, nullable=False)
    deduction_method: Mapped[DeductionMethod] = mapped_column(
        SAEnum(DeductionMethod, native_enum=False, length=20), nullable=False
    )
    deductions: Mapped[list] = mapped_column(JSON, nullable=False)  # [{label, amount}]
    total_deduction: Mapped[int] = mapped_column(Integer, nullable=False)
    net: Mapped[int] = mapped_column(Integer, nullable=False)
    basis: Mapped[dict] = mapped_column(JSON, nullable=False)  # {new_sales, renewal_sales, session_signs}

    # ── 제출·결재 워크플로우 (직원 신청 → 대표자 승인/반려) ──
    status: Mapped[PayslipStatus] = mapped_column(
        SAEnum(PayslipStatus, native_enum=False, length=20),
        nullable=False,
        default=PayslipStatus.DRAFT,
        server_default="DRAFT",
    )
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
