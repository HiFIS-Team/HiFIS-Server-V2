"""근태·휴가 DTO — CLAUDE.md §6.9."""

from datetime import date, datetime

from app.enums import AttendanceSource, LeaveStatus, LeaveType
from app.schemas.base import CamelModel


class AttendanceOut(CamelModel):
    id: str
    employee_id: str
    date: date
    check_in: datetime | None = None
    check_out: datetime | None = None
    work_minutes: int | None = None
    source: AttendanceSource


class LeaveRequestCreate(CamelModel):
    type: LeaveType
    start_date: date
    end_date: date
    reason: str | None = None


class LeaveRequestOut(CamelModel):
    id: str
    employee_id: str
    type: LeaveType
    start_date: date
    end_date: date
    days: float
    reason: str | None = None
    status: LeaveStatus
