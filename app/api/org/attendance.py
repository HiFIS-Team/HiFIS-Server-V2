"""근태·휴가 라우터 — CLAUDE.md §6.9.

/attendance/scan: 바코드 → 출/퇴근 토글(근무시간 자동). /leaves: 신청·승인/거절.
목록은 지점 스코프(MEMBER=본인 지점).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user, require_role
from app.core.periods import period_range
from app.db.session import get_db
from app.enums import AttendanceSource, LeaveStatus, LeaveType, Role
from app.models.org.attendance import Attendance, LeaveRequest
from app.models.org.employee import Employee
from app.schemas.org.attendance import (
    AttendanceOut,
    AttendanceScanRequest,
    LeaveRequestCreate,
    LeaveRequestOut,
)
from app.services.notifications import notify

router = APIRouter(tags=["attendance"])


# ---------- 근태 ----------
@router.post("/attendance/scan", response_model=AttendanceOut)
async def scan_attendance(
    payload: AttendanceScanRequest | None = Body(default=None),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Attendance:
    # 사번(emp_no) 스캔이면 그 주인(지점 스캐너 모드), 없으면 로그인 본인(하위호환)
    if payload is not None and payload.code:
        normalized = payload.code.strip().replace("-", "")  # 하이픈 유무 모두 허용
        target = await db.scalar(
            select(Employee).where(
                func.replace(Employee.emp_no, "-", "") == normalized,
                Employee.deleted_at.is_(None),
            )
        )
        if target is None:
            raise HTTPException(404, detail={"code": "EMP_NO_NOT_FOUND", "message": "등록되지 않은 사번입니다"})
        if current.role != Role.ADMIN and target.branch_id != current.branch_id:
            raise HTTPException(403, detail={"code": "OTHER_BRANCH", "message": "다른 지점 직원은 스캔할 수 없습니다"})
    else:
        target = current

    now = datetime.now(timezone.utc)
    today = now.date()
    record = (
        await db.execute(
            select(Attendance).where(
                Attendance.employee_id == target.id, Attendance.date == today
            )
        )
    ).scalar_one_or_none()

    if record is None:  # 첫 스캔 = 출근
        record = Attendance(
            employee_id=target.id, date=today, check_in=now, source=AttendanceSource.BARCODE
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
    verb = "승인" if status == LeaveStatus.APPROVED else "반려"
    await notify(
        db,
        employee_id=leave.employee_id,
        type="LEAVE",
        title=f"휴가 신청이 {verb}되었습니다",
        body=f"{leave.start_date} ~ {leave.end_date}",
        link="/attendance",
    )
    await db.commit()
    await db.refresh(leave)
    return leave


@router.post("/leaves/{request_id}/approve", response_model=LeaveRequestOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def approve_leave(request_id: str, db: AsyncSession = Depends(get_db)) -> LeaveRequest:
    return await _decide_leave(request_id, LeaveStatus.APPROVED, db)


@router.post("/leaves/{request_id}/reject", response_model=LeaveRequestOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def reject_leave(request_id: str, db: AsyncSession = Depends(get_db)) -> LeaveRequest:
    return await _decide_leave(request_id, LeaveStatus.REJECTED, db)


@router.post("/leaves/{request_id}/cancel", response_model=LeaveRequestOut)
async def cancel_leave(
    request_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeaveRequest:
    """신청자 본인이 대기중(PENDING) 휴가를 취소 → CANCELLED (이력 보존)."""
    leave = await db.get(LeaveRequest, request_id)
    if leave is None:
        raise HTTPException(404, detail={"code": "LEAVE_NOT_FOUND", "message": "휴가 신청을 찾을 수 없습니다"})
    if leave.employee_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 신청만 취소할 수 있습니다"})
    if leave.status != LeaveStatus.PENDING:
        raise HTTPException(400, detail={"code": "NOT_CANCELLABLE", "message": "대기중 신청만 취소할 수 있습니다"})
    leave.status = LeaveStatus.CANCELLED
    await db.commit()
    await db.refresh(leave)
    return leave
