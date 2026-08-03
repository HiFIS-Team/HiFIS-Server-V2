"""Employee (직원) 모델 — CLAUDE.md §2.2.

wire(Employee)엔 없는 password_hash 는 DB 전용 컬럼 (응답 직렬화 안 함).
"""

from datetime import datetime

from sqlalchemy import ARRAY, DateTime, Enum as SAEnum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.enums import DeductionMethod, EmployeeStatus, Rank, Role, WorkStatus


class Employee(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "employees"

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # 세션 폐기용 버전 — 로그아웃/비번변경 시 +1 → 그 이전 발급 토큰(access·refresh) 전부 무효(§M2)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 사번(사람이 읽는 식별자) — {입사연도}-{4자리 순번}. 프로필 + 출근 스캔 공용, 자동발급 후 불변
    emp_no: Mapped[str | None] = mapped_column(String(16), unique=True, index=True, nullable=True)

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

    avatar_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#2F54EB")  # 팔레트 첫 색(§2.2)
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

    # 기본 근무 시간 (§6.9) — "HH:MM" KST. 최초 1회 본인 설정 → 잠금(본인·관리자 모두 변경 경로 없음).
    # 스캔이 이 시각보다 30분+ 이르거나 늦으면 근무 외 출근 점수 자동 적립. null = 아직 미설정(첫 로그인 게이트).
    shift_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    shift_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    # 근무 요일 — ISO 요일 1(월)~7(일) 배열. null=미설정. 결근 판정 기준(근무일인데 기록 없으면 결근).
    work_days: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
