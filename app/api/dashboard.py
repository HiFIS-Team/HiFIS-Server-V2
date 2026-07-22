"""대시보드 라우터 — ADMIN/MANAGER 지점 요약 집계 (CLAUDE.md §6.13).

branchId 지정 시 해당 지점, 생략 시 전체 지점. period 생략 시 이번 달.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.core.periods import current_period, period_range
from app.db.session import get_db
from app.enums import (
    EmployeeStatus,
    LeaveStatus,
    RegistrationType,
    Role,
)
from app.models.attendance import Attendance, LeaveRequest
from app.models.employee import Employee
from app.models.member import Member
from app.models.registration import Registration
from app.models.score_event import ScoreEvent
from app.schemas.dashboard import DashboardOut, SalesSummary, ScoreSummary

router = APIRouter(tags=["dashboard"])


@router.get(
    "/dashboard",
    response_model=DashboardOut,
    dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))],
)
async def dashboard(
    branch_id: str | None = Query(None, alias="branchId"),
    period: str = Query(default_factory=current_period),
    db: AsyncSession = Depends(get_db),
) -> DashboardOut:
    start, end = period_range(period)
    today = datetime.now(timezone.utc).date()

    # 재직 직원 수
    head_stmt = select(func.count()).select_from(Employee).where(
        Employee.status == EmployeeStatus.ACTIVE, Employee.deleted_at.is_(None)
    )
    if branch_id:
        head_stmt = head_stmt.where(Employee.branch_id == branch_id)
    headcount = await db.scalar(head_stmt) or 0

    # 점수 — 기간 합계 + 카테고리별
    score_stmt = (
        select(ScoreEvent.category, func.coalesce(func.sum(ScoreEvent.points), 0))
        .where(ScoreEvent.period == period)
        .group_by(ScoreEvent.category)
    )
    if branch_id:
        score_stmt = score_stmt.where(ScoreEvent.branch_id == branch_id)
    by_category: dict[str, int] = {}
    total_score = 0
    for category, pts in (await db.execute(score_stmt)).all():
        by_category[category.value] = int(pts)
        total_score += int(pts)

    # 매출 — 등록(Registration)을 회원 지점 기준으로 집계
    new_sum = func.coalesce(
        func.sum(case((Registration.type == RegistrationType.NEW, Registration.price_paid), else_=0)),
        0,
    )
    sales_stmt = (
        select(
            func.coalesce(func.sum(Registration.price_paid), 0),
            func.count(),
            new_sum,
        )
        .select_from(Registration)
        .join(Member, Registration.member_id == Member.id)
        .where(Registration.purchased_at >= start, Registration.purchased_at < end)
    )
    if branch_id:
        sales_stmt = sales_stmt.where(Member.branch_id == branch_id)
    sales_total, sales_count, sales_new = (await db.execute(sales_stmt)).one()

    # 오늘 출근 체크인 수
    checkin_stmt = (
        select(func.count())
        .select_from(Attendance)
        .join(Employee, Attendance.employee_id == Employee.id)
        .where(Attendance.date == today, Attendance.check_in.is_not(None))
    )
    if branch_id:
        checkin_stmt = checkin_stmt.where(Employee.branch_id == branch_id)
    checked_in_today = await db.scalar(checkin_stmt) or 0

    # 대기중 휴가
    leave_stmt = (
        select(func.count())
        .select_from(LeaveRequest)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .where(LeaveRequest.status == LeaveStatus.PENDING)
    )
    if branch_id:
        leave_stmt = leave_stmt.where(Employee.branch_id == branch_id)
    leaves_pending = await db.scalar(leave_stmt) or 0

    return DashboardOut(
        branch_id=branch_id,
        period=period,
        headcount=int(headcount),
        scores=ScoreSummary(total=total_score, by_category=by_category),
        sales=SalesSummary(
            total=int(sales_total),
            count=int(sales_count),
            new=int(sales_new),
            renewal=int(sales_total) - int(sales_new),
        ),
        checked_in_today=int(checked_in_today),
        leaves_pending=int(leaves_pending),
    )
