"""개인 홈 요약 라우터 — GET /me/home (모든 직원 첫 화면, [SELF]).

지점 요약인 /dashboard(ADMIN,MANAGER)와 달리 권한 없이 '본인 것만' 준다:
오늘 근태 · 내 미완료 프로젝트 수 · 안 읽은 공지 수 · 이번 달 내 점수.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# 오늘 근태 판정은 근태 라우터의 로직을 재사용(정상/지각/조기퇴근 등 동일 기준)
from app.api.staff.attendance import _absent_today, _attendance_status
from app.core.deps import get_current_user, require_role
from app.core.periods import KST, current_period
from app.db.session import get_db
from app.enums import (
    ApprovalStatus,
    AttendanceStatus,
    EventStatus,
    InboxKind,
    LeaveStatus,
    LeaveType,
    PayslipStatus,
    Role,
)
from app.models.board.approval import Approval
from app.models.board.event import Event
from app.models.board.notice import Notice
from app.models.board.notice_read import NoticeRead
from app.models.payroll.payslip import Payslip
from app.models.projects.project import Project
from app.models.scoring.score_event import ScoreEvent
from app.models.staff.attendance import Attendance, LeaveRequest
from app.models.staff.employee import Employee
from app.schemas.staff.home import HomeAttendanceOut, HomeSummaryOut, InboxItemOut

router = APIRouter(tags=["home"])


@router.get("/me/home", response_model=HomeSummaryOut)
async def my_home(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HomeSummaryOut:
    now_kst = datetime.now(timezone.utc).astimezone(KST)
    today = now_kst.date()
    period = current_period()

    # ── 오늘 근태: 기록 있으면 판정 / 없으면 휴가·휴무 / 그래도 없으면 '출근 전'(status=null) ──
    rec = (
        await db.execute(
            select(Attendance).where(
                Attendance.employee_id == current.id, Attendance.date == today
            )
        )
    ).scalar_one_or_none()
    att = HomeAttendanceOut()
    if rec is not None:
        att = HomeAttendanceOut(
            status=_attendance_status(rec, current.shift_start, current.shift_end, today),
            check_in=rec.check_in,
            check_out=rec.check_out,
            work_minutes=rec.work_minutes,
        )
    else:
        lv = (
            await db.execute(
                select(LeaveRequest).where(
                    LeaveRequest.employee_id == current.id,
                    LeaveRequest.status == LeaveStatus.APPROVED,
                    LeaveRequest.start_date <= today,
                    LeaveRequest.end_date >= today,
                )
            )
        ).scalars().first()
        if lv is not None:
            att = HomeAttendanceOut(
                status=AttendanceStatus.ON_LEAVE, leave_type=lv.type, half_period=lv.half_period
            )
        elif current.work_days and today.isoweekday() not in set(current.work_days):
            att = HomeAttendanceOut(status=AttendanceStatus.DAY_OFF)
        elif current.work_days and _absent_today(current, now_kst):
            # 근무일인데 퇴근 시간이 지나도록 스캔이 없다 → 결근
            att = HomeAttendanceOut(status=AttendanceStatus.ABSENT)
        # else: 아직 근무 시간 안이다 → 미출근(status=null)

    # ── 내 미완료 프로젝트 수 (담당자에 나 포함 & progress<100) ──
    incomplete = await db.scalar(
        select(func.count())
        .select_from(Project)
        .where(Project.assignee_ids.contains([current.id]), Project.progress < 100)
    )

    # ── 안 읽은 공지 수 = 내 NoticeRead 가 없는 공지 (읽음 상태 기준, §6.4) ──
    unread = await db.scalar(
        select(func.count())
        .select_from(Notice)
        .where(
            ~select(NoticeRead.id)
            .where(NoticeRead.notice_id == Notice.id, NoticeRead.employee_id == current.id)
            .exists()
        )
    )

    # ── 이번 달 내 점수 합 ──
    month_score = await db.scalar(
        select(func.coalesce(func.sum(ScoreEvent.points), 0)).where(
            ScoreEvent.employee_id == current.id, ScoreEvent.period == period
        )
    )

    return HomeSummaryOut(
        period=period,
        today_attendance=att,
        incomplete_projects=int(incomplete or 0),
        unread_notices=int(unread or 0),
        month_score=int(month_score or 0),
    )


# 월차 종류를 화면 말로 — 앱의 신청 화면과 같은 이름을 쓴다
_LEAVE_LABEL = {
    LeaveType.ANNUAL: "연차",
    LeaveType.HALF: "반차",
    LeaveType.SICK: "병가",
    LeaveType.FIELD: "외근",
    LeaveType.ETC: "기타",
}


@router.get(
    "/me/inbox",
    response_model=list[InboxItemOut],
    dependencies=[Depends(require_role(Role.ADMIN))],  # MASTER 자동 승계
)
async def my_inbox(db: AsyncSession = Depends(get_db)) -> list[InboxItemOut]:
    """결재를 기다리는 것 — 급여·월차·전자결재·일정을 한 목록으로 (홈 카드).

    **전사 기준이다.** ADMIN 은 결재선에 없어서 '내 차례'로 세면 늘 비는데,
    지켜보는 자리라 목록은 같이 봐야 한다. 승인·반려 버튼만 앱이 MASTER 에게 낸다.

    올린 지 오래된 것부터 준다 — 오래 묵은 게 먼저 처리돼야 한다.
    """
    items: list[InboxItemOut] = []

    for slip in (
        await db.scalars(
            select(Payslip).where(Payslip.status == PayslipStatus.SUBMITTED)
        )
    ).all():
        year, month = slip.year_month.split("-")
        items.append(
            InboxItemOut(
                kind=InboxKind.PAYSLIP,
                id=slip.id,
                employee_id=slip.employee_id,
                title=f"{year}년 {int(month)}월 급여",
                detail=f"실수령 {slip.net:,}원",
                created_at=slip.updated_at,  # 제출한 시각(마지막 상태 변경)
            )
        )

    for leave in (
        await db.scalars(
            select(LeaveRequest).where(LeaveRequest.status == LeaveStatus.PENDING)
        )
    ).all():
        span = (
            f"{leave.start_date.month}.{leave.start_date.day}"
            if leave.start_date == leave.end_date
            else f"{leave.start_date.month}.{leave.start_date.day}"
            f" ~ {leave.end_date.month}.{leave.end_date.day}"
        )
        days = int(leave.days) if leave.days == int(leave.days) else leave.days
        items.append(
            InboxItemOut(
                kind=InboxKind.LEAVE,
                id=leave.id,
                employee_id=leave.employee_id,
                title=_LEAVE_LABEL.get(leave.type, "월차"),
                detail=f"{span} · {days}일",
                created_at=leave.created_at,
            )
        )

    for doc in (
        await db.scalars(
            select(Approval).where(Approval.status == ApprovalStatus.IN_PROGRESS)
        )
    ).all():
        items.append(
            InboxItemOut(
                kind=InboxKind.APPROVAL,
                id=doc.id,
                employee_id=doc.requester_id,
                title=doc.kind,
                detail=doc.title,
                created_at=doc.created_at,
            )
        )

    for event in (
        await db.scalars(select(Event).where(Event.status == EventStatus.PENDING))
    ).all():
        start = event.start_at.astimezone(KST)
        end = event.end_at.astimezone(KST)
        span = (
            f"{start.month}.{start.day}"
            if start.date() == end.date()
            else f"{start.month}.{start.day} ~ {end.month}.{end.day}"
        )
        items.append(
            InboxItemOut(
                kind=InboxKind.EVENT,
                id=event.id,
                employee_id=event.owner_id,
                title=event.title,
                detail=f"{span} · {event.category}",
                created_at=event.created_at,
            )
        )

    items.sort(key=lambda item: item.created_at)
    return items
