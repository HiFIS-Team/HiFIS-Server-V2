"""근태·휴가 DTO — CLAUDE.md §6.9."""

from datetime import date, datetime

from pydantic import AliasChoices, Field

from app.enums import AttendanceSource, AttendanceStatus, HalfPeriod, LeaveStatus, LeaveType
from app.schemas.base import CamelModel


class AttendanceScanRequest(CamelModel):
    # 지점 스캐너가 읽은 사번(emp_no). 생략 시 로그인 본인 스캔(하위호환).
    # 입력 키는 code / barcode 모두 허용(구 스캐너 호환), 하이픈 유무 무관.
    code: str | None = Field(default=None, validation_alias=AliasChoices("code", "barcode"))


class AttendanceOut(CamelModel):
    id: str
    employee_id: str
    date: date
    check_in: datetime | None = None
    check_out: datetime | None = None
    work_minutes: int | None = None
    source: AttendanceSource
    status: AttendanceStatus | None = None  # 서버 판정(정상/지각/조기퇴근 등) — 근무시간 대비


class AttendanceRosterGroupOut(CamelModel):
    """하루 안에서 같은 판정을 받은 사람들."""

    status: AttendanceStatus
    names: list[str]


class AttendanceRosterDayOut(CamelModel):
    """전사 캘린더 하루 — 상태별로 누가 그랬는지.

    사람별 캘린더를 인원수만큼 부르지 않으려고 한 번에 묶어 준다.
    휴무(DAY_OFF)·판정불가는 담지 않는다 — 화면에 쓸 자리가 없다.
    """

    date: date
    groups: list[AttendanceRosterGroupOut]


class AttendanceDayOut(CamelModel):
    """캘린더 하루 상태 — 기록 없는 날(결근/휴가/휴무)까지 포함해 서버가 판정."""

    date: date
    status: AttendanceStatus
    check_in: datetime | None = None
    check_out: datetime | None = None
    work_minutes: int | None = None
    leave_type: LeaveType | None = None    # ON_LEAVE 일 때 휴가 종류
    half_period: HalfPeriod | None = None  # 반차면 오전/오후


class LeaveRequestCreate(CamelModel):
    type: LeaveType
    half_period: HalfPeriod | None = None  # type=HALF 면 필수(오전/오후)
    start_date: date
    end_date: date
    reason: str | None = None


class LeaveBalanceOut(CamelModel):
    granted: float    # 부여 일수(입사일 기준 근로기준법 산정)
    used: float       # 사용(승인)+신청중(대기) 확정 일수 — 이번 연차연도
    remaining: float  # 잔여 = granted - used


class LeaveReject(CamelModel):
    # 반려는 사유 필수
    reason: str = Field(min_length=1)


class LeaveRequestOut(CamelModel):
    id: str
    employee_id: str
    type: LeaveType
    half_period: HalfPeriod | None = None
    start_date: date
    end_date: date
    days: float
    reason: str | None = None
    reject_reason: str | None = None
    status: LeaveStatus
