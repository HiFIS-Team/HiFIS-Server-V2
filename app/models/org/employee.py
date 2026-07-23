"""Employee (직원) 모델 — CLAUDE.md §2.2.

wire(Employee)엔 없는 password_hash 는 DB 전용 컬럼 (응답 직렬화 안 함).
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.enums import DeductionMethod, EmployeeStatus, Rank, Role, WorkStatus


class Employee(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "employees"

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # 출근 스캐너용 고유 바코드(사번/뱃지) — 모든 생성 경로에서 자동발급 (§6.9)
    barcode: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)

    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=False, index=True
    )
    # rank(직급)은 채용 시점에 확정 — 초대키/승인에서 지정되어 항상 채워짐
    rank: Mapped[Rank] = mapped_column(SAEnum(Rank, native_enum=False, length=20), nullable=False)
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

    # 급여 공제 방식 (§5) — 직원별 설정
    deduction_method: Mapped[DeductionMethod] = mapped_column(
        SAEnum(DeductionMethod, native_enum=False, length=20),
        nullable=False,
        default=DeductionMethod.FREELANCE,
        server_default=DeductionMethod.FREELANCE.value,
    )
