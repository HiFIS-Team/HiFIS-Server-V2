"""Employee DTO — CLAUDE.md §2.2."""

from datetime import datetime

from pydantic import Field, field_validator

from app.enums import AttendanceStatus, DeductionMethod, EmployeeStatus, EmploymentType, Rank, Role, WorkStatus
from app.schemas.base import CamelModel, SignedUrlOptional, normalize_phone


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
    # 정규직 ↔ 알바 — 급여 계산 방식이 갈린다
    employment_type: EmploymentType | None = None
    role: Role | None = None
    status: EmployeeStatus | None = None
    team: str | None = None
    branch_id: str | None = None
    phone: str | None = None
    deduction_method: DeductionMethod | None = None  # 급여 공제 방식 (§5)


class EmployeeMeUpdate(CamelModel):
    name: str | None = None
    phone: str | None = None  # 본인 휴대폰 번호 (§2.2) — 직원이 직접 입력
    avatar_color: str | None = None
    avatar_url: str | None = None
    status_message: str | None = None
    work_status: WorkStatus | None = None

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v is not None else None


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
    employment_type: EmploymentType
    avatar_color: str
    avatar_url: SignedUrlOptional = None
    status_message: str | None = None
    work_status: WorkStatus
    joined_at: datetime
    resigned_at: datetime | None = None  # 퇴사 시각 (§58) — null=재직 중
    # 계정 정지 (이용약관 제8조 1항) — null 이면 정상.
    # **재직 상태와 다른 축이다** — 정지돼도 재직 중이라 조직도에는 그대로 선다
    suspended_at: datetime | None = None
    suspend_reason: str | None = None
    last_active_at: datetime | None = None
    # 처음 로그인한 시각 — null 이면 가입만 하고 아직 안 들어온 사람이다
    first_login_at: datetime | None = None
    shift_start: str | None = None  # 기본 근무 시간 "HH:MM" (null=미설정 → 첫 로그인 시 설정 유도)
    shift_end: str | None = None
    work_days: list[int] | None = None  # 근무 요일 ISO 1(월)~7(일). null=미설정
    # 오늘 근태 판정 (§59) — 목록(GET /employees)에서만 채움. 그 외 응답은 null.
    today_attendance_status: AttendanceStatus | None = None


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
