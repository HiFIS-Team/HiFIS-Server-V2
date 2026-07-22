"""근태·휴가 라우터 — CLAUDE.md §6.9.

/attendance/scan: 바코드 → 출/퇴근 토글(근무시간 자동). /leaves: 신청·승인/거절.
목록은 지점 스코프(MEMBER=본인 지점).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user, require_role
from app.core.periods import period_range
from app.db.session import get_db
from app.enums import AttendanceSource, LeaveStatus, LeaveType, Role
from app.models.attendance import Attendance, LeaveRequest
from app.models.employee import Employee
from app.schemas.attendance import AttendanceOut, LeaveRequestCreate, LeaveRequestOut

router = APIRouter(tags=["attendance"])


# ---------- 근태 ----------
@router.post("/attendance/scan", response_model=AttendanceOut)
async def scan_attendance(
    current: Employee = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Attendance:
    now = datetime.now(timezone.utc)
    today = now.date()
    record = (
        await db.execute(
            select(Attendance).where(
                Attendance.employee_id == current.id, Attendance.date == today
            )
        )
    ).scalar_one_or_none()

    if record is None:  # 첫 스캔 = 출근
        record = Attendance(
            employee_id=current.id, date=today, check_in=now, source=AttendanceSource.BARCODE
        )
        db.add(record)
    else:  # 두 번째 이후 = 퇴근(근무시간 갱신)
        record.check_out = now
        if record.check_in is not None:
            record.work_minutes = int((now - record.check_in).total_seconds() // 60)
    await db.commit()
    await db.refresh(record)
    return record


@router.get("/attendance", response_model=list[AttendanceOut])
async def list_attendance(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    employee_id: str | None = Query(None, alias="employeeId"),
    month: str | None = Query(None),
) -> list[Attendance]:
    stmt = select(Attendance)
    if scope:
        stmt = stmt.join(Employee, Employee.id == Attendance.employee_id).where(
            Employee.branch_id == scope
        )
    if employee_id:
        stmt = stmt.where(Attendance.employee_id == employee_id)
    if month:
        start, end = period_range(month)
        stmt = stmt.where(Attendance.date >= start.date(), Attendance.date < end.date())
    result = await db.execute(stmt.order_by(Attendance.date.desc()))
    return list(result.scalars().all())


# ---------- 휴가 ----------
def _compute_days(leave_type: LeaveType, start, end) -> float:
    if leave_type == LeaveType.HALF:
        return 0.5
    return float((end - start).days + 1)


@router.get("/leaves", response_model=list[LeaveRequestOut])
async def list_leaves(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    employee_id: str | None = Query(None, alias="employeeId"),
    status: LeaveStatus | None = Query(None),
) -> list[LeaveRequest]:
    stmt = select(LeaveRequest)
    if scope:
        stmt = stmt.join(Employee, Employee.id == LeaveRequest.employee_id).where(
            Employee.branch_id == scope
        )
    if employee_id:
        stmt = stmt.where(LeaveRequest.employee_id == employee_id)
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    result = await db.execute(stmt.order_by(LeaveRequest.start_date.desc()))
    return list(result.scalars().all())


@router.post("/leaves", response_model=LeaveRequestOut, status_code=201)
async def create_leave(
    payload: LeaveRequestCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeaveRequest:
    if payload.end_date < payload.start_date:
        raise HTTPException(400, detail={"code": "INVALID_RANGE", "message": "종료일이 시작일보다 빠릅니다"})
    leave = LeaveRequest(
        employee_id=current.id,
        type=payload.type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        days=_compute_days(payload.type, payload.start_date, payload.end_date),
        reason=payload.reason,
    )
    db.add(leave)
    await db.commit()
    await db.refresh(leave)
    return leave


async def _decide_leave(request_id: str, status: LeaveStatus, db: AsyncSession) -> LeaveRequest:
    leave = await db.get(LeaveRequest, request_id)
    if leave is None:
        raise HTTPException(404, detail={"code": "LEAVE_NOT_FOUND", "message": "휴가 신청을 찾을 수 없습니다"})
    if leave.status != LeaveStatus.PENDING:
        raise HTTPException(400, detail={"code": "ALREADY_HANDLED", "message": "이미 처리된 신청입니다"})
    leave.status = status
    await db.commit()
    await db.refresh(leave)
    return leave


@router.post("/leaves/{request_id}/approve", response_model=LeaveRequestOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def approve_leave(request_id: str, db: AsyncSession = Depends(get_db)) -> LeaveRequest:
    return await _decide_leave(request_id, LeaveStatus.APPROVED, db)


@router.post("/leaves/{request_id}/reject", response_model=LeaveRequestOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def reject_leave(request_id: str, db: AsyncSession = Depends(get_db)) -> LeaveRequest:
    return await _decide_leave(request_id, LeaveStatus.REJECTED, db)
