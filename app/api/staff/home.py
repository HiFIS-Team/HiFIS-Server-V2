"""개인 홈 요약 라우터 — GET /me/home (모든 직원 첫 화면, [SELF]).

지점 요약인 /dashboard(ADMIN,MANAGER)와 달리 권한 없이 '본인 것만' 준다:
오늘 근태 · 내 미완료 프로젝트 수 · 안 읽은 공지 수 · 이번 달 내 점수.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# 오늘 근태 판정은 근태 라우터의 로직을 재사용(정상/지각/조기퇴근 등 동일 기준)
from app.api.staff.attendance import _attendance_status
from app.core.deps import get_current_user
from app.core.periods import KST, current_period
from app.db.session import get_db
from app.enums import ApprovalStatus, AttendanceStatus, LeaveStatus, PayslipStatus, Role
from app.models.board.approval import Approval
from app.models.board.notice import Notice
from app.models.board.notice_read import NoticeRead
from app.models.payroll.payslip import Payslip
from app.models.projects.project import Project
from app.models.scoring.score_event import ScoreEvent
from app.models.staff.attendance import Attendance, LeaveRequest
from app.models.staff.employee import Employee
from app.schemas.staff.home import HomeAttendanceOut, HomePendingOut, HomeSummaryOut

router = APIRouter(tags=["home"])


@router.get("/me/home", response_model=HomeSummaryOut)
async def my_home(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HomeSummaryOut:
    today = datetime.now(timezone.utc).astimezone(KST).date()
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
        # else: 근무일인데 아직 기록 없음 → 출근 전(status=null). 오늘은 결근 판정 안 함.

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

    # ── 결재를 기다리는 것 (MASTER·ADMIN 만) ──
    # 대표·관리자는 출근을 안 해서 홈의 출퇴근 카드가 늘 비어 있다.
    # 그 자리에 놓을 '지금 눌러야 할 것'을 여기서 같이 실어 준다 —
    # 앱이 따로 세면 홈 한 장에 요청이 4개가 된다.
    pending = None
    if current.role in (Role.MASTER, Role.ADMIN):
        pending = HomePendingOut(
            approvals=int(
                await db.scalar(
                    select(func.count())
                    .select_from(Approval)
                    .where(Approval.status == ApprovalStatus.IN_PROGRESS)
                )
                or 0
            ),
            payslips=int(
                await db.scalar(
                    select(func.count())
                    .select_from(Payslip)
                    .where(Payslip.status == PayslipStatus.SUBMITTED)
                )
                or 0
            ),
            leaves=int(
                await db.scalar(
                    select(func.count())
                    .select_from(LeaveRequest)
                    .where(LeaveRequest.status == LeaveStatus.PENDING)
                )
                or 0
            ),
        )

    return HomeSummaryOut(
        period=period,
        today_attendance=att,
        incomplete_projects=int(incomplete or 0),
        unread_notices=int(unread or 0),
        month_score=int(month_score or 0),
        pending=pending,
    )
