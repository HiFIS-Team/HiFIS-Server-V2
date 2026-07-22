"""Employee (직원) 모델 — CLAUDE.md §2.2.

wire(Employee)엔 없는 password_hash 는 DB 전용 컬럼 (응답 직렬화 안 함).
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.enums import EmployeeStatus, Rank, Role, WorkStatus


class Employee(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "employees"

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=False, index=True
    )
    # rank(직급)은 급여 속성 — 초대 가입 시엔 미배정(null), 관리자가 이후 배정
    rank: Mapped[Rank | None] = mapped_column(SAEnum(Rank, native_enum=False, length=20), nullable=True)
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, native_enum=False, length=20), nullable=False, default=Role.MEMBER
    )
    team: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[EmployeeStatus] = mapped_column(
        SAEnum(EmployeeStatus, native_enum=False, length=20),
        nullable=False,
        default=EmployeeStatus.ACTIVE,
    )

    avatar_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#6366f1")
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    work_status: Mapped[WorkStatus] = mapped_column(
        SAEnum(WorkStatus, native_enum=False, length=20),
        nullable=False,
        default=WorkStatus.AUTO,
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
