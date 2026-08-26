"""개인 홈 요약 라우터 — GET /me/home (모든 직원 첫 화면, [SELF]).

지점 요약인 /dashboard(ADMIN,MANAGER)와 달리 권한 없이 '본인 것만' 준다:
오늘 근태 · 내 미완료 프로젝트 수 · 안 읽은 공지 수 · 이번 달 내 점수.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# 오늘 근태 판정은 근태 라우터의 로직을 재사용(정상/지각/조기퇴근 등 동일 기준)
from app.api.staff.attendance import (
    _absent_today,
    _attendance_status,
    _just_left_overnight,
    _still_overnight,
)
from app.core.deps import get_current_user, require_role
from app.core.periods import KST, current_period
from app.db.session import get_db
from app.enums import (
    ApprovalStatus,
    AttendanceStatus,
    EventStatus,
    InboxKind,
    InboxStatus,
    LeaveStatus,
    LeaveType,
    MyTaskRequestType,
    PayslipStatus,
    ProjectRequestStatus,
    ProjectRequestType,
    Role,
)
from app.models.board.approval import Approval
from app.models.board.event import Event
from app.models.board.notice import Notice
from app.models.board.notice_read import NoticeRead
from app.models.payroll.payslip import Payslip
from app.models.projects.project import Project
from app.models.projects.project_request import ProjectRequest
from app.models.scoring.my_task import MyTask, MyTaskMiss, MyTaskRequest
from app.models.scoring.score_event import ScoreEvent
from app.models.staff.attendance import Attendance, LeaveRequest
from app.models.staff.employee import Employee
from app.schemas.staff.home import HomeAttendanceOut, HomeSummaryOut, InboxItemOut
from app.services.notice_visibility import is_notice_blocked

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
            status=_attendance_status(
                rec,
                current.shift_start,
                current.shift_end,
                now_kst,
                current.joined_at.astimezone(KST).date(),
            ),
            check_in=rec.check_in,
            check_out=rec.check_out,
            work_minutes=rec.work_minutes,
        )
    else:
        prev = (
            await db.execute(
                select(Attendance).where(
                    Attendance.employee_id == current.id,
                    Attendance.date == today - timedelta(days=1),
                )
            )
        ).scalar_one_or_none()
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
        if _still_overnight(prev, now_kst):
            # 자정을 넘겨서도 안 갔다 — 계속 야근이다
            att = HomeAttendanceOut(
                status=AttendanceStatus.OVERTIME,
                check_in=prev.check_in,
                work_minutes=prev.work_minutes,
            )
        elif _just_left_overnight(prev, now_kst):
            # 자정을 넘겨 퇴근했다 — 잠깐은 '퇴근'으로 두고 그 뒤 미출근으로 돌아간다
            att = HomeAttendanceOut(
                status=AttendanceStatus.NORMAL,
                check_in=prev.check_in,
                check_out=prev.check_out,
                work_minutes=prev.work_minutes,
            )
        elif lv is not None:
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
    unread = 0
    if not await is_notice_blocked(db, current):
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


#: 종류마다 상태 이름이 달라서 앱의 세 칸에 뭐가 들어가는지를 여기서 정한다.
#: **본인이 물린 것(월차 취소·결재 회수)은 반려 칸에 같이 넣는다** — 흔치 않아
#: 탭을 따로 두면 늘 비고, 전자결재 화면도 회수를 반려 탭에 두고 있다.
_PAYSLIP_IN = {
    InboxStatus.PENDING: (PayslipStatus.SUBMITTED,),
    # 지급 완료도 승인을 거친 것이다 — 결재 이력에서 빠지면 안 된다
    InboxStatus.APPROVED: (PayslipStatus.APPROVED, PayslipStatus.PAID),
    InboxStatus.REJECTED: (PayslipStatus.REJECTED,),
}
_LEAVE_IN = {
    InboxStatus.PENDING: (LeaveStatus.PENDING,),
    InboxStatus.APPROVED: (LeaveStatus.APPROVED,),
    InboxStatus.REJECTED: (LeaveStatus.REJECTED, LeaveStatus.CANCELLED),
}
_APPROVAL_IN = {
    InboxStatus.PENDING: (ApprovalStatus.IN_PROGRESS,),
    InboxStatus.APPROVED: (ApprovalStatus.APPROVED,),
    InboxStatus.REJECTED: (ApprovalStatus.REJECTED, ApprovalStatus.WITHDRAWN),
}
#: 내 업무 수정·삭제 — 프로젝트 결재와 같은 상태 enum 을 쓴다
_MY_TASK_IN = {
    InboxStatus.PENDING: (ProjectRequestStatus.PENDING,),
    InboxStatus.APPROVED: (ProjectRequestStatus.APPROVED,),
    InboxStatus.REJECTED: (ProjectRequestStatus.REJECTED,),
}
#: 프로젝트 기한 연장·누락 사유·수정·삭제 — 내 업무와 같은 enum
_PROJECT_IN = _MY_TASK_IN

#: 프로젝트 신청 종류를 화면 말로 — 앱 프로젝트 화면과 같은 이름을 쓴다
_PROJECT_LABEL = {
    ProjectRequestType.EXTENSION: "기한 연장",
    ProjectRequestType.OVERDUE: "누락 사유",
    ProjectRequestType.EDIT: "프로젝트 수정",
    ProjectRequestType.DELETE: "프로젝트 삭제",
}


@router.get(
    "/me/inbox",
    response_model=list[InboxItemOut],
    dependencies=[Depends(require_role(Role.ADMIN))],  # MASTER 자동 승계
)
async def my_inbox(
    status: InboxStatus = Query(InboxStatus.PENDING),
    db: AsyncSession = Depends(get_db),
) -> list[InboxItemOut]:
    """결재 목록 — 승인·반려를 받는 것을 **여섯 계열 전부** 한 목록으로.

    급여 · 월차 · 전자결재 · 일정 · 내 업무 · **프로젝트**. 승인·반려 엔드포인트가
    있는데 여기 없으면 대표가 홈에서 영영 못 본다 (프로젝트가 실제로 그랬다 —
    대기 3건이 묻혀 있었다, 2026-08-14).

    **전사 기준이다.** ADMIN 은 결재선에 없어서 '내 차례'로 세면 늘 비는데,
    지켜보는 자리라 목록은 같이 봐야 한다. 승인·반려 버튼만 앱이 MASTER 에게 낸다.

    `status` 가 앱 결재 화면의 `대기 · 승인 · 반려` 탭이다 (기본 `PENDING` —
    홈 카드가 인자 없이 부른다). **대기는 오래 묵은 것부터**(먼저 처리돼야 한다),
    **처리된 것은 최근 것부터** 준다.

    **일정 반려는 목록에 없다** — 반려하면 행을 지우기 때문이다(`EventStatus`).
    승인된 일정도 **결재를 거친 것만** 센다 (`Event.decided_at`).
    """
    # (정렬 키, 줄) — 종류마다 처리 시각을 들고 있는 칸이 달라서 따로 모은다
    rows: list[tuple[datetime, InboxItemOut]] = []
    pending = status is InboxStatus.PENDING

    for slip in (
        await db.scalars(select(Payslip).where(Payslip.status.in_(_PAYSLIP_IN[status])))
    ).all():
        year, month = slip.year_month.split("-")
        rows.append(
            (
                slip.updated_at if pending else (slip.decided_at or slip.updated_at),
                InboxItemOut(
                    kind=InboxKind.PAYSLIP,
                    id=slip.id,
                    employee_id=slip.employee_id,
                    title=f"{year}년 {int(month)}월 급여",
                    detail=f"실수령 {slip.net:,}원",
                    created_at=slip.updated_at,  # 제출한 시각(마지막 상태 변경)
                ),
            )
        )

    for leave in (
        await db.scalars(
            select(LeaveRequest).where(LeaveRequest.status.in_(_LEAVE_IN[status]))
        )
    ).all():
        span = (
            f"{leave.start_date.month}.{leave.start_date.day}"
            if leave.start_date == leave.end_date
            else f"{leave.start_date.month}.{leave.start_date.day}"
            f" ~ {leave.end_date.month}.{leave.end_date.day}"
        )
        days = int(leave.days) if leave.days == int(leave.days) else leave.days
        rows.append(
            (
                leave.created_at if pending else leave.updated_at,
                InboxItemOut(
                    kind=InboxKind.LEAVE,
                    id=leave.id,
                    employee_id=leave.employee_id,
                    title=_LEAVE_LABEL.get(leave.type, "월차"),
                    detail=f"{span} · {days}일",
                    created_at=leave.created_at,
                ),
            )
        )

    for doc in (
        await db.scalars(select(Approval).where(Approval.status.in_(_APPROVAL_IN[status])))
    ).all():
        rows.append(
            (
                doc.created_at if pending else doc.updated_at,
                InboxItemOut(
                    kind=InboxKind.APPROVAL,
                    id=doc.id,
                    employee_id=doc.requester_id,
                    title=doc.kind,
                    detail=doc.title,
                    created_at=doc.created_at,
                ),
            )
        )

    # 일정만 승인 칸에 조건이 하나 더 붙는다.
    # **`decided_at` 이 있는 것만** — 없으면 대표가 올려서 그냥 선 일정이라,
    # 상태만 보면 전사 달력이 통째로 결재 이력에 서 버린다.
    if status is InboxStatus.APPROVED:
        event_q = select(Event).where(
            Event.status == EventStatus.APPROVED, Event.decided_at.isnot(None)
        )
    else:
        event_q = select(Event).where(
            Event.status
            == (
                EventStatus.PENDING
                if status is InboxStatus.PENDING
                else EventStatus.REJECTED
            )
        )

    for event in (await db.scalars(event_q)).all():
        start = event.start_at.astimezone(KST)
        end = event.end_at.astimezone(KST)
        span = (
            f"{start.month}.{start.day}"
            if start.date() == end.date()
            else f"{start.month}.{start.day} ~ {end.month}.{end.day}"
        )
        rows.append(
            (
                event.created_at if pending else (event.decided_at or event.updated_at),
                InboxItemOut(
                    kind=InboxKind.EVENT,
                    id=event.id,
                    employee_id=event.owner_id,
                    title=event.title,
                    detail=f"{span} · {event.category}",
                    created_at=event.created_at,
                ),
            )
        )

    for req in (
        await db.scalars(
            select(MyTaskRequest).where(MyTaskRequest.status.in_(_MY_TASK_IN[status]))
        )
    ).all():
        task = await db.get(MyTask, req.my_task_id)
        # 무엇을 어떻게 고치겠다는 건지 한 줄로 — 결재하는 사람이 봐야 하는 값이다
        if req.type == MyTaskRequestType.EDIT:
            detail = f"{task.content if task else ''} → {(req.payload or {}).get('content', '')}"
        else:
            detail = task.content if task else ""
        rows.append(
            (
                req.created_at if pending else (req.decided_at or req.updated_at),
                InboxItemOut(
                    kind=InboxKind.MY_TASK,
                    id=req.id,
                    employee_id=req.requested_by_id,
                    title=f"내 업무 {'수정' if req.type == MyTaskRequestType.EDIT else '삭제'}",
                    detail=detail,
                    created_at=req.created_at,
                ),
            )
        )

    # 누락 사유서 — 수정·삭제 결재와 같은 함에 선다 (2026-08-21).
    # **사유서를 낸 것만** 온다. 안 낸 누락은 결재할 것이 없어서 여기 안 선다
    for miss in (
        await db.scalars(
            select(MyTaskMiss).where(MyTaskMiss.excuse_status.in_(_MY_TASK_IN[status]))
        )
    ).all():
        day = miss.date
        rows.append(
            (
                miss.created_at if pending else (miss.decided_at or miss.updated_at),
                InboxItemOut(
                    kind=InboxKind.TASK_MISS,
                    id=miss.id,
                    employee_id=miss.employee_id,
                    title="업무 누락 사유",
                    detail=f"{day.month}월 {day.day}일 · {miss.task_count}개",
                    created_at=miss.created_at,
                ),
            )
        )

    for req in (
        await db.scalars(
            select(ProjectRequest).where(ProjectRequest.status.in_(_PROJECT_IN[status]))
        )
    ).all():
        project = await db.get(Project, req.project_id)
        title = project.title if project else "지워진 프로젝트"
        # 무엇을 해 달라는 건지 한 줄로 — 종류마다 봐야 하는 값이 다르다
        if req.type in (ProjectRequestType.EXTENSION, ProjectRequestType.OVERDUE):
            due = req.new_due.astimezone(KST).date() if req.new_due else None
            detail = f"{title} · {due.month}.{due.day}까지" if due else title
        else:
            detail = title
        rows.append(
            (
                req.created_at if pending else (req.decided_at or req.updated_at),
                InboxItemOut(
                    kind=InboxKind.PROJECT,
                    id=req.id,
                    employee_id=req.requested_by_id,
                    title=_PROJECT_LABEL.get(req.type, "프로젝트"),
                    detail=detail,
                    created_at=req.created_at,
                ),
            )
        )

    # 대기는 오래된 것부터(먼저 처리돼야 한다), 처리된 것은 최근 것부터
    rows.sort(key=lambda row: row[0], reverse=not pending)
    return [item for _, item in rows]
