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


class HomePendingOut(CamelModel):
    """결재를 기다리는 것 — **MASTER · ADMIN 에게만 실린다.**

    대표·관리자는 출근을 안 해서 홈의 출퇴근 카드가 늘 비어 있다.
    그 자리에 '지금 눌러야 할 것'을 대신 놓으려고 만든 묶음이다.

    셋 다 **전사 기준**이다 — ADMIN 은 승인 권한이 없어서 '내 차례'로 세면
    늘 0이 된다. 건수는 같이 보고 승인·반려 버튼만 MASTER 에게 나간다.
    """

    approvals: int = 0  # 아직 안 끝난 전자결재(IN_PROGRESS)
    payslips: int = 0   # 제출된 급여(SUBMITTED)
    leaves: int = 0     # 대기중 월차(PENDING)


class HomeSummaryOut(CamelModel):
    period: str                           # "YYYY-MM" (이번 달)
    today_attendance: HomeAttendanceOut
    incomplete_projects: int              # 내가 담당인 미완료(progress<100) 프로젝트 수
    unread_notices: int                   # 안 읽은 공지 수
    month_score: int                      # 이번 달 내 점수 합

    # MASTER·ADMIN 이 아니면 null — 나머지 직원 홈은 모양이 그대로다
    pending: HomePendingOut | None = None
