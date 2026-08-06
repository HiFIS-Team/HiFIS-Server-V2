"""Payslip (급여명세서) 모델 — CLAUDE.md §5.

대부분 계산 결과 스냅샷. 원천(Registration 매출, RankPolicy)에서 산출해 저장.
(employee_id, year_month) 유니크 — 재생성 시 교체.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
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

    #: 서버가 계산한 원래 커미션 — 위 두 값과 다르면 본인이 고쳐서 신청한 것이다.
    #:
    #: 고친 값으로 덮어써 버리면 **무엇을 승인하는지 아무도 모른다.**
    #: 자동 집계가 빠뜨린 수업(대타·기록 누락)을 바로잡으라고 연 자리라,
    #: 원래 값이 남아야 결재하는 쪽이 차이를 보고 판단한다.
    #: (null = 이 규칙이 생기기 전에 만들어진 명세서)
    incentive_new_auto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    incentive_renewal_auto: Mapped[int | None] = mapped_column(Integer, nullable=True)

    other_allowances: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross: Mapped[int] = mapped_column(Integer, nullable=False)
    deduction_method: Mapped[DeductionMethod] = mapped_column(
        SAEnum(DeductionMethod, native_enum=False, length=20), nullable=False
    )
    deductions: Mapped[list] = mapped_column(JSON, nullable=False)  # [{label, amount}]
    total_deduction: Mapped[int] = mapped_column(Integer, nullable=False)
    net: Mapped[int] = mapped_column(Integer, nullable=False)
    basis: Mapped[dict] = mapped_column(JSON, nullable=False)  # {new_sales, renewal_sales, session_signs}

    #: 실제 지급일 — 만들 때 그 사람의 규칙(PaydayPolicy)으로 찍어 둔다.
    #:
    #: `year_month` 에서 다시 계산하면 **나중에 규칙이 바뀌었을 때 옛 명세서의
    #: 날짜까지 따라 움직인다.** 이미 준 돈의 날짜가 바뀌면 안 된다.
    #: (null = 규칙이 생기기 전에 만들어진 명세서 — 말일로 떨어진다)
    pay_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── 제출·결재 워크플로우 (직원 신청 → 대표자 승인/반려) ──
    status: Mapped[PayslipStatus] = mapped_column(
        SAEnum(PayslipStatus, native_enum=False, length=20),
        nullable=False,
        default=PayslipStatus.DRAFT,
        server_default="DRAFT",
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 신청 특이사항(지각 사유·추가 근무 등) — 대표가 결재 시 참고
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 실지급 처리 시각
