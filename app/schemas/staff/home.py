"""개인 홈 요약 DTO — GET /me/home (home_screen.dart 첫 화면 카드)."""

from datetime import datetime

from app.enums import AttendanceStatus, HalfPeriod, InboxKind, LeaveType
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


class InboxItemOut(CamelModel):
    """결재를 기다리는 것 한 줄 — GET /me/inbox (MASTER·ADMIN).

    급여·월차·전자결재는 테이블이 따로인데 홈 카드에서는 **한 목록**으로 선다.
    앱이 셋을 각각 받아 합치면 홈 첫 화면에서만 요청이 세 개 더 나가서,
    서버가 미리 합쳐 준다.

    `title`·`detail` 은 화면에 그대로 찍는 문장이다. 종류마다 꺼낼 필드가
    달라서(급여는 달·실수령, 월차는 기간·일수) 앱에서 만들면 분기만 늘어난다.
    """

    kind: InboxKind
    id: str                  # 그 종류의 승인·반려 엔드포인트에 넘길 id
    employee_id: str         # 올린 사람
    title: str               # `2026년 7월 급여` · `연차` · `외근·출장`
    detail: str              # 한 줄 요약
    created_at: datetime
