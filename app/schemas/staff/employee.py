"""Employee DTO — CLAUDE.md §2.2."""

from datetime import datetime

from pydantic import Field, field_validator

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
    shift_start: str | None = None  # 기본 근무 시간 "HH:MM" (null=미설정 → 첫 로그인 시 설정 유도)
    shift_end: str | None = None
    work_days: list[int] | None = None  # 근무 요일 ISO 1(월)~7(일). null=미설정


class ScheduleSet(CamelModel):
    # 온보딩 근무 설정 (근무 시간 밖에서만 수정 가능). "HH:MM" 24시간 + 근무 요일.
    shift_start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    shift_end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    work_days: list[int] = Field(min_length=1)  # ISO 요일 1(월)~7(일), 최소 1일

    @field_validator("work_days")
    @classmethod
    def _valid_work_days(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("근무일은 1(월)~7(일) 사이여야 합니다")
        return sorted(set(v))
