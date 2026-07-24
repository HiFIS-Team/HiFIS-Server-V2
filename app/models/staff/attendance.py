"""근태·휴가 모델 — Attendance · LeaveRequest (CLAUDE.md §6.9)."""

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import AttendanceSource, LeaveStatus, LeaveType


class Attendance(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("employee_id", "date", name="uq_attendance_day"),)

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    work_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[AttendanceSource] = mapped_column(
        SAEnum(AttendanceSource, native_enum=False, length=20),
        nullable=False,
        default=AttendanceSource.BARCODE,
    )


class LeaveRequest(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "leave_requests"

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    type: Mapped[LeaveType] = mapped_column(
        SAEnum(LeaveType, native_enum=False, length=20), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 신청 사유
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 반려 사유(관리자)
    status: Mapped[LeaveStatus] = mapped_column(
        SAEnum(LeaveStatus, native_enum=False, length=20),
        nullable=False,
        default=LeaveStatus.PENDING,
    )
