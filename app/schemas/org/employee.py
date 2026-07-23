"""Employee DTO — CLAUDE.md §2.2."""

from datetime import datetime

from app.enums import DeductionMethod, EmployeeStatus, Rank, Role, WorkStatus
from app.schemas.base import CamelModel


class EmployeeCreate(CamelModel):
    name: str
    email: str
    password: str
    branch_id: str
    rank: Rank
    role: Role = Role.MEMBER
    team: str | None = None
    phone: str | None = None
    avatar_color: str | None = None
    barcode: str | None = None  # 미지정 시 서버 자동발급 (사번 직접 지정 가능)


class EmployeeUpdate(CamelModel):
    rank: Rank | None = None
    role: Role | None = None
    status: EmployeeStatus | None = None
    team: str | None = None
    branch_id: str | None = None
    phone: str | None = None
    deduction_method: DeductionMethod | None = None  # 급여 공제 방식 (§5)


class EmployeeMeUpdate(CamelModel):
    name: str | None = None
    avatar_color: str | None = None
    avatar_url: str | None = None
    status_message: str | None = None
    work_status: WorkStatus | None = None


class PasswordChange(CamelModel):
    current_password: str
    new_password: str


class EmployeeOut(CamelModel):
    id: str
    name: str
    email: str
    phone: str | None = None
    barcode: str | None = None  # PWA 가 이 값을 바코드/QR 로 렌더 → 지점 스캐너로 스캔
    branch_id: str
    rank: Rank
    role: Role
    team: str | None = None
    status: EmployeeStatus
    avatar_color: str
    avatar_url: str | None = None
    status_message: str | None = None
    work_status: WorkStatus
    joined_at: datetime
    last_active_at: datetime | None = None
