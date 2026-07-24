"""Employee DTO — CLAUDE.md §2.2."""

from datetime import datetime

from pydantic import Field

from app.enums import DeductionMethod, EmployeeStatus, Rank, Role, WorkStatus
from app.schemas.base import CamelModel, SignedUrlOptional


class EmployeeCreate(CamelModel):
    name: str
    email: str
    password: str = Field(min_length=8)  # 비밀번호 정책 — 최소 8자
    branch_id: str
    rank: Rank
    role: Role = Role.MEMBER
    team: str | None = None
    phone: str | None = None
    avatar_color: str | None = None


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
    new_password: str = Field(min_length=8)


class EmployeeOut(CamelModel):
    id: str
    name: str
    email: str
    phone: str | None = None
    emp_no: str | None = None  # 사번 {입사연도}-{순번} — PWA 가 바코드로 렌더, 스캔 조회 키
    branch_id: str
    rank: Rank
    role: Role
    team: str | None = None
    status: EmployeeStatus
    avatar_color: str
    avatar_url: SignedUrlOptional = None
    status_message: str | None = None
    work_status: WorkStatus
    joined_at: datetime
    last_active_at: datetime | None = None
