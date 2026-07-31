"""근태·휴가 라우터 — CLAUDE.md §6.9.

/attendance/scan: 바코드 → 출/퇴근 토글(근무시간 자동). /leaves: 신청·승인/거절.
목록은 지점 스코프(MEMBER=본인 지점).
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user, require_role
from app.core.periods import KST, period_range
from app.db.session import get_db
from app.enums import (
    AttendanceSource,
    AttendanceStatus,
    HalfPeriod,
    LeaveStatus,
    LeaveType,
    Role,
    ScoreCategory,
)
from app.models.scoring.score_event import ScoreEvent
from app.models.staff.attendance import Attendance, LeaveRequest
from app.models.staff.employee import Employee
from app.schemas.staff.attendance import (
    AttendanceOut,
    AttendanceScanRequest,
    LeaveBalanceOut,
    LeaveReject,
    LeaveRequestCreate,
    LeaveRequestOut,
)
from app.services import notification_texts as ntext
from app.services.notifications import notify
from app.services.scoring import accrue_score

router = APIRouter(tags=["attendance"])

# 근무 외 출근 자동 점수 (§6.9) — 기본 근무시간보다 이 분수 이상 이르거나 늦으면 인정, 각 +점수(하루 최대 2회).
OFFHOURS_THRESHOLD_MIN = 30
OFFHOURS_POINTS = 10


def _hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _kst_min(dt: datetime) -> int:
    k = dt.astimezone(KST)
    return k.hour * 60 + k.minute


def _attendance_status(
    rec: Attendance, shift_start: str | None, shift_end: str | None, today: date
) -> AttendanceStatus:
    """근무시간 대비 판정(§6.9) — 정상/지각/조기퇴근. 근무시간 미설정이면 UNKNOWN.

    결근(근무일인데 기록 없음)은 근무 요일 스케줄이 없어 여기서 판정하지 않는다.
    """
    if not shift_start or not shift_end or rec.check_in is None:
        return AttendanceStatus.UNKNOWN
    late = _kst_min(rec.check_in) > _hhmm_to_min(shift_start)
    if rec.check_out is None:
        return AttendanceStatus.IN_PROGRESS if rec.date >= today else AttendanceStatus.NO_CHECKOUT
    early = _kst_min(rec.check_out) < _hhmm_to_min(shift_end)
    if late and early:
        return AttendanceStatus.LATE_AND_EARLY
    if late:
        return AttendanceStatus.LATE
    if early:
        return AttendanceStatus.EARLY_LEAVE
    return AttendanceStatus.NORMAL


async def _award_offhours(
    db: AsyncSession, target: Employee, day_key: str, ref_suffix: str, kind_label: str
) -> None:
    """근무외출근 자동 점수 — (직원·근무일·방향)당 1회만 적립(퇴근 재스캔 멱등). 시스템 발생이라 created_by=None."""
    ref = f"offhours:{day_key}:{ref_suffix}"
    exists = await db.scalar(
        select(ScoreEvent).where(
            ScoreEvent.employee_id == target.id,
            ScoreEvent.source_ref_id == ref,
        )
    )
    if exists is not None:
        return
    await accrue_score(
        db,
        employee_id=target.id,
        branch_id=target.branch_id,
        category=ScoreCategory.CONTRIB,
        points=OFFHOURS_POINTS,
        reason=f"{kind_label} (자동)",
        source_ref_id=ref,
    )
    await notify(db, employee_id=target.id, **ntext.offhours_award(kind_label, OFFHOURS_POINTS))


# ---------- 근태 ----------
@router.post("/attendance/scan", response_model=AttendanceOut)
async def scan_attendance(
    payload: AttendanceScanRequest | None = Body(default=None),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttendanceOut:
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
        if current.role not in (Role.MASTER, Role.ADMIN) and target.branch_id != current.branch_id:
            raise HTTPException(403, detail={"code": "OTHER_BRANCH", "message": "다른 지점 직원은 스캔할 수 없습니다"})
    else:
        target = current

    now = datetime.now(timezone.utc)
    now_kst = now.astimezone(KST)
    today = now_kst.date()  # KST 근무일 기준(자정 넘는 UTC 분리 방지 → 이른 출근도 같은 날 퇴근과 페어링)
    now_min = now_kst.hour * 60 + now_kst.minute
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
        action = "출근"
        # 기본 출근보다 30분+ 이르게 왔으면 조기출근 자동 점수
        if target.shift_start and now_min <= _hhmm_to_min(target.shift_start) - OFFHOURS_THRESHOLD_MIN:
            await _award_offhours(db, target, today.isoformat(), "in", "조기 출근")
    else:  # 두 번째 이후 = 퇴근(근무시간 갱신)
        record.check_out = now
        if record.check_in is not None:
            record.work_minutes = int((now - record.check_in).total_seconds() // 60)
        action = "퇴근"
        # 기본 퇴근보다 30분+ 늦게 찍으면 초과근무 자동 점수(재스캔해도 하루 1회만)
        if target.shift_end and now_min >= _hhmm_to_min(target.shift_end) + OFFHOURS_THRESHOLD_MIN:
            await _award_offhours(db, target, today.isoformat(), "out", "초과 근무")
    # 스캔 즉시 알림(+웹푸시) — 스캔한 본인에게
    await notify(db, employee_id=target.id, **ntext.attendance_scan(action, now_kst))
    await db.commit()
    await db.refresh(record)
    out = AttendanceOut.model_validate(record)
    out.status = _attendance_status(record, target.shift_start, target.shift_end, now_kst.date())
    return out


@router.get("/attendance", response_model=list[AttendanceOut])
async def list_attendance(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    employee_id: str | None = Query(None, alias="employeeId"),
    month: str | None = Query(None),
) -> list[AttendanceOut]:
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
    rows = list((await db.execute(stmt.order_by(Attendance.date.desc()))).scalars().all())
    # 직원별 근무시간 로드 → 판정(정상/지각/조기퇴근)
    emp_ids = {r.employee_id for r in rows}
    shifts: dict[str, tuple[str | None, str | None]] = {}
    if emp_ids:
        for eid, ss, se in (
            await db.execute(
                select(Employee.id, Employee.shift_start, Employee.shift_end).where(
                    Employee.id.in_(emp_ids)
                )
            )
        ).all():
            shifts[eid] = (ss, se)
    today = datetime.now(timezone.utc).astimezone(KST).date()
    out: list[AttendanceOut] = []
    for r in rows:
        ss, se = shifts.get(r.employee_id, (None, None))
        o = AttendanceOut.model_validate(r)
        o.status = _attendance_status(r, ss, se, today)
        out.append(o)
    return out


# ---------- 휴가 ----------
def _compute_days(leave_type: LeaveType, start, end) -> float:
    if leave_type == LeaveType.HALF:
        return 0.5
    return float((end - start).days + 1)


def annual_leave_granted(joined: date, as_of: date) -> float:
    """근로기준법 제60조 연차 부여(입사일 기준).

    - 계속근로 1년 미만: 1개월 개근 1일씩(최대 11) — 개근은 경과 개월수로 단순화.
    - 1년 이상: 15일 + (근속연수-1)//2 가산(3년차부터 2년마다 1일), 최대 25일.
    """
    months = (as_of.year - joined.year) * 12 + (as_of.month - joined.month)
    if as_of.day < joined.day:
        months -= 1
    months = max(months, 0)
    years = months // 12
    if years < 1:
        return float(min(months, 11))
    return float(min(15 + (years - 1) // 2, 25))


def _leave_year_start(joined: date, as_of: date) -> date:
    """이번 연차연도 시작 = as_of 이전의 가장 최근 입사기념일."""

    def anniv(year: int) -> date:
        try:
            return joined.replace(year=year)
        except ValueError:  # 2/29 입사
            return joined.replace(year=year, month=2, day=28)

    a = anniv(as_of.year)
    return a if a <= as_of else anniv(as_of.year - 1)


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


@router.get("/leaves/balance", response_model=LeaveBalanceOut)
async def leave_balance(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    employee_id: str | None = Query(None, alias="employeeId"),
) -> LeaveBalanceOut:
    """연차 부여/사용/잔여 — 입사일 기준 근로기준법 산정. 기본 본인, employeeId 지정은 매니저↑."""
    target = current
    if employee_id and employee_id != current.id:
        if current.role not in (Role.MASTER, Role.ADMIN, Role.MANAGER):
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "권한이 없습니다"})
        target = await db.get(Employee, employee_id)
        if target is None or target.deleted_at is not None:
            raise HTTPException(404, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원을 찾을 수 없습니다"})
        if current.role == Role.MANAGER and target.branch_id != current.branch_id:
            raise HTTPException(403, detail={"code": "OTHER_BRANCH", "message": "다른 지점 직원은 조회할 수 없습니다"})

    as_of = datetime.now(timezone.utc).astimezone(KST).date()
    joined = target.joined_at.astimezone(KST).date()
    granted = annual_leave_granted(joined, as_of)
    year_start = _leave_year_start(joined, as_of)
    # 사용=승인+대기(신청중) 연차/반차 — 이번 연차연도. 병가·외근·기타는 연차 차감 아님.
    used_raw = await db.scalar(
        select(func.coalesce(func.sum(LeaveRequest.days), 0.0)).where(
            LeaveRequest.employee_id == target.id,
            LeaveRequest.type.in_([LeaveType.ANNUAL, LeaveType.HALF]),
            LeaveRequest.status.in_([LeaveStatus.APPROVED, LeaveStatus.PENDING]),
            LeaveRequest.start_date >= year_start,
        )
    )
    used = float(used_raw or 0.0)
    return LeaveBalanceOut(granted=granted, used=used, remaining=granted - used)


@router.post("/leaves", response_model=LeaveRequestOut, status_code=201)
async def create_leave(
    payload: LeaveRequestCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeaveRequest:
    if payload.end_date < payload.start_date:
        raise HTTPException(400, detail={"code": "INVALID_RANGE", "message": "종료일이 시작일보다 빠릅니다"})
    # 반차면 오전/오후 필수, 그 외 타입은 시간대 무시(null)
    half_period = None
    if payload.type == LeaveType.HALF:
        if payload.half_period is None:
            raise HTTPException(400, detail={"code": "HALF_PERIOD_REQUIRED", "message": "반차는 오전/오후를 선택해야 합니다"})
        half_period = payload.half_period
    leave = LeaveRequest(
        employee_id=current.id,
        type=payload.type,
        half_period=half_period,
        start_date=payload.start_date,
        end_date=payload.end_date,
        days=_compute_days(payload.type, payload.start_date, payload.end_date),
        reason=payload.reason,
    )
    db.add(leave)
    await db.commit()
    await db.refresh(leave)
    return leave


async def _decide_leave(
    request_id: str, status: LeaveStatus, db: AsyncSession, reason: str | None = None
) -> LeaveRequest:
    leave = await db.get(LeaveRequest, request_id)
    if leave is None:
        raise HTTPException(404, detail={"code": "LEAVE_NOT_FOUND", "message": "휴가 신청을 찾을 수 없습니다"})
    if leave.status != LeaveStatus.PENDING:
        raise HTTPException(400, detail={"code": "ALREADY_HANDLED", "message": "이미 처리된 신청입니다"})
    leave.status = status
    if status == LeaveStatus.REJECTED:
        leave.reject_reason = reason
    await notify(
        db,
        employee_id=leave.employee_id,
        **ntext.leave_decision(status == LeaveStatus.APPROVED, leave.start_date, leave.end_date, reason),
    )
    await db.commit()
    await db.refresh(leave)
    return leave


@router.post("/leaves/{request_id}/approve", response_model=LeaveRequestOut, dependencies=[Depends(require_role(Role.MASTER, Role.MANAGER))])
async def approve_leave(request_id: str, db: AsyncSession = Depends(get_db)) -> LeaveRequest:
    return await _decide_leave(request_id, LeaveStatus.APPROVED, db)


@router.post("/leaves/{request_id}/reject", response_model=LeaveRequestOut, dependencies=[Depends(require_role(Role.MASTER, Role.MANAGER))])
async def reject_leave(
    request_id: str, payload: LeaveReject, db: AsyncSession = Depends(get_db)
) -> LeaveRequest:
    return await _decide_leave(request_id, LeaveStatus.REJECTED, db, payload.reason)


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
