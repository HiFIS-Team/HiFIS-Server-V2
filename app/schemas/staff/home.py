"""개인 홈 요약 DTO — GET /me/home (home_screen.dart 첫 화면 카드)."""

from datetime import datetime

from app.enums import AttendanceStatus, HalfPeriod, LeaveType
from app.schemas.base import CamelModel


class HomeAttendanceOut(CamelModel):
    """오늘 근태 — status=null 이면 아직 출근 전(기록 없음)."""

    status: AttendanceStatus | None = None
    check_in: datetime | None = None
    check_out: datetime | None = None
    work_minutes: int | None = None
    leave_type: LeaveType | None = None    # ON_LEAVE 일 때 휴가 종류
    half_period: HalfPeriod | None = None  # 반차면 오전/오후


class HomeSummaryOut(CamelModel):
    period: str                           # "YYYY-MM" (이번 달)
    today_attendance: HomeAttendanceOut
    incomplete_projects: int              # 내가 담당인 미완료(progress<100) 프로젝트 수
    unread_notices: int                   # 안 읽은 공지 수
    month_score: int                      # 이번 달 내 점수 합
