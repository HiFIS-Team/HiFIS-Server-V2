"""Payslip 라우터 — 급여명세서 산출·조회·신청·결재 (CLAUDE.md §5).

POST /generate [ADMIN]: 지점·월 대상 산출(재생성=교체). GET /me [SELF], GET [ADMIN,MANAGER].
직원 신청 → 대표자 승인/반려: GET /me/window · POST /me/submit · POST /{id}/approve · /reject.
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.periods import period_range
from app.db.session import get_db
from app.enums import EmploymentType, PayslipStatus, Role
from app.models.staff.employee import Employee
from app.models.payroll.payslip import Payslip
from app.schemas.payroll.payslip import (
    AccruedOut,
    PaydayWindowOut,
    PayslipGenerateRequest,
    PayslipOut,
    PayslipReject,
    PayslipSubmit,
)
from app.services import notification_texts as ntext
from app.services.notifications import notify
from app.services.payroll import (
    NoScheduleError,
    apply_incentive_override,
    build_hourly_payslip_data,
    can_adjust_incentive,
    build_payslip_data,
    compute_payday,
    generate_branch_payslips,
    get_hourly_wage,
    get_payday_policy,
    get_rank_policy,
    payday_window,
    payroll_month_of,
    payroll_started,
    payroll_window,
)

router = APIRouter(prefix="/payslips", tags=["payslips"])


@router.post("/generate", response_model=list[PayslipOut], dependencies=[Depends(require_role(Role.ADMIN))])
async def generate_payslips(
    payload: PayslipGenerateRequest, db: AsyncSession = Depends(get_db)
) -> list[Payslip]:
    generated = await generate_branch_payslips(db, payload.branch_id, payload.year_month)
    await db.commit()
    for payslip in generated:
        await db.refresh(payslip)
    return generated


@router.get("/me", response_model=PayslipOut)
async def my_payslip(
    year_month: str = Query(..., alias="yearMonth"),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Payslip:
    payslip = (
        await db.execute(
            select(Payslip).where(
                Payslip.employee_id == current.id, Payslip.year_month == year_month
            )
        )
    ).scalar_one_or_none()
    if payslip is None:
        raise HTTPException(404, detail={"code": "PAYSLIP_NOT_FOUND", "message": "해당 월 명세서가 없습니다"})
    return payslip


@router.get("/me/window", response_model=PaydayWindowOut)
async def my_payday_window(
    year_month: str = Query(..., alias="yearMonth"),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaydayWindowOut:
    """급여 신청 창(지급일 여부). 지급일 당일만 신청 가능.

    지급일은 **지점×직급마다 다르다** — 화순·FC 는 말일, 동광주·첨단 트레이너는 익월 10일.
    """
    start, _ = period_range(year_month)
    payday = await get_payday_policy(db, current.branch_id, current.rank, start)
    return PaydayWindowOut(**payday_window(year_month, date.today(), payday))


@router.get("/me/accrued", response_model=AccruedOut)
async def my_accrued(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccruedOut:
    """이번 주기에 **지금까지 쌓인 PT 커미션** — 기본급은 빼고 커미션만.

    확정 명세서는 지급일에 나오는데, 그 전까지는 얼마 쌓였는지 볼 길이 없었다.
    세션 싸인을 찍을 때마다 바로 오르고 주기가 넘어가면 0 부터 다시 센다.

    알바(시급제)와 요율 정책이 없는 직급은 커미션 자체가 없어 0 으로 돌아간다.
    """
    today = date.today()
    now = datetime.now(timezone.utc)
    payday = await get_payday_policy(db, current.branch_id, current.rank, now)
    year_month = payroll_month_of(today, payday)
    start, end = payroll_window(year_month, payday)
    empty = AccruedOut(
        year_month=year_month,
        period_start=start.date(),
        period_end=end.date(),
        payday=compute_payday(year_month, payday),
        incentive_new=0,
        incentive_renewal=0,
        total=0,
        session_signs=0,
        new_sessions=0,
        renewal_sessions=0,
        can_adjust=False,
    )
    # 아직 재기 시작 전이면 0 이다 — 앱을 켜기 전 실적을 쌓아 보여주면 안 된다
    if not payroll_started(year_month, payday):
        return empty
    if current.employment_type == EmploymentType.PART_TIME:
        return empty  # 알바는 시급제 — PT 커미션이 없다
    policy = await get_rank_policy(db, current.rank, current.branch_id, start)
    if policy is None:
        return empty
    data = await build_payslip_data(db, current, year_month, policy, payday)
    can_adjust = can_adjust_incentive(current, policy)
    return AccruedOut(
        year_month=year_month,
        period_start=start.date(),
        period_end=end.date(),
        payday=compute_payday(year_month, payday),
        incentive_new=data["incentive_new"],
        incentive_renewal=data["incentive_renewal"],
        total=data["incentive_new"] + data["incentive_renewal"],
        session_signs=data["basis"]["session_signs"],
        new_sessions=len(data["basis"]["new_sales"]),
        renewal_sessions=len(data["basis"]["renewal_sales"]),
        can_adjust=can_adjust,
    )


@router.post("/me/submit", response_model=PayslipOut)
async def submit_my_payslip(
    payload: PayslipSubmit,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Payslip:
    """본인 급여 신청(제출). 지급일 당일만 가능 → DRAFT/REJECTED → SUBMITTED. 명세서 없으면 즉석 산출."""
    start, _ = period_range(payload.year_month)
    payday = await get_payday_policy(db, current.branch_id, current.rank, start)
    if not payday_window(payload.year_month, date.today(), payday)["is_open"]:
        raise HTTPException(403, detail={"code": "NOT_PAYDAY", "message": "급여 지급일에만 신청할 수 있어요"})
    if not payroll_started(payload.year_month, payday):
        raise HTTPException(400, detail={"code": "PAYROLL_NOT_STARTED", "message": "아직 급여를 재기 시작한 기간이 아니에요"})
    rank_policy = await get_rank_policy(db, current.rank, current.branch_id, start)
    adjusting = payload.incentive_new is not None or payload.incentive_renewal is not None
    # 커미션을 고쳐 보낼 수 있는 사람인지 먼저 본다 — 알바·FC 는 고칠 자리가 없다.
    # 조용히 무시하면 **적어 낸 금액과 신청된 금액이 달라진다.**
    if adjusting and not can_adjust_incentive(current, rank_policy):
        raise HTTPException(
            400,
            detail={"code": "NO_INCENTIVE", "message": "PT 커미션이 없는 급여라 금액을 고칠 수 없어요"},
        )

    payslip = (
        await db.execute(
            select(Payslip).where(
                Payslip.employee_id == current.id, Payslip.year_month == payload.year_month
            )
        )
    ).scalar_one_or_none()
    if payslip is None:
        if current.employment_type == EmploymentType.PART_TIME:
            # 알바는 시급제 — 신청·결재 절차는 정규직과 같고 계산만 다르다
            wage = await get_hourly_wage(db, current.branch_id, start)
            if wage is None:
                raise HTTPException(400, detail={"code": "NO_HOURLY_WAGE", "message": "시급 정책이 없어 신청할 수 없어요"})
            try:
                data = await build_hourly_payslip_data(db, current, payload.year_month, wage, payday)
            except NoScheduleError:
                raise HTTPException(400, detail={"code": "NO_SCHEDULE", "message": "근무 시간을 설정해야 급여를 신청할 수 있어요"})
        else:
            if rank_policy is None:
                raise HTTPException(400, detail={"code": "NO_RANK_POLICY", "message": "직급 급여 정책이 없어 신청할 수 없어요"})
            data = await build_payslip_data(db, current, payload.year_month, rank_policy, payday)
        data = apply_incentive_override(
            data, current, payload.incentive_new, payload.incentive_renewal
        )
        payslip = Payslip(employee_id=current.id, year_month=payload.year_month, **data)
        db.add(payslip)
        await db.flush()
    elif adjusting:
        # 마감으로 이미 만들어져 있던 명세서 — 고친 값만 얹고 총액을 다시 센다
        data = apply_incentive_override(
            {
                "base_salary": payslip.base_salary,
                "incentive_new": payslip.incentive_new,
                "incentive_renewal": payslip.incentive_renewal,
                "other_allowances": payslip.other_allowances,
            },
            current,
            payload.incentive_new,
            payload.incentive_renewal,
        )
        for field, value in data.items():
            setattr(payslip, field, value)
    if payslip.status in (PayslipStatus.SUBMITTED, PayslipStatus.APPROVED, PayslipStatus.PAID):
        raise HTTPException(400, detail={"code": "ALREADY_SUBMITTED", "message": "이미 제출된 명세서예요"})
    payslip.status = PayslipStatus.SUBMITTED
    payslip.note = payload.note  # 특이사항(재제출 시 갱신)
    payslip.submitted_at = datetime.now(timezone.utc)
    payslip.reject_reason = None
    payslip.decided_at = None
    payslip.decided_by_id = None
    await db.commit()
    await db.refresh(payslip)
    return payslip


@router.post("/me/cancel", response_model=PayslipOut)
async def cancel_my_payslip(
    year_month: str = Query(..., alias="yearMonth"),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Payslip:
    """본인 급여 신청 취소(제출 철회) — SUBMITTED → DRAFT. 승인·지급된 뒤에는 불가."""
    payslip = (
        await db.execute(
            select(Payslip).where(
                Payslip.employee_id == current.id, Payslip.year_month == year_month
            )
        )
    ).scalar_one_or_none()
    if payslip is None:
        raise HTTPException(404, detail={"code": "PAYSLIP_NOT_FOUND", "message": "해당 월 명세서가 없습니다"})
    if payslip.status != PayslipStatus.SUBMITTED:
        raise HTTPException(400, detail={"code": "NOT_SUBMITTED", "message": "제출 대기 중인 신청만 취소할 수 있어요"})
    payslip.status = PayslipStatus.DRAFT
    payslip.submitted_at = None  # note 는 유지(재신청 시 재사용)
    await db.commit()
    await db.refresh(payslip)
    return payslip


@router.get("/me/list", response_model=list[PayslipOut])
async def my_payslip_list(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None, alias="to"),
) -> list[Payslip]:
    """본인 명세서 목록(히스토리·추이) — yearMonth "YYYY-MM" 범위(포함). 범위 생략 시 전체, 최신순."""
    stmt = select(Payslip).where(Payslip.employee_id == current.id)
    if from_:
        stmt = stmt.where(Payslip.year_month >= from_)  # "YYYY-MM" 문자열 정렬 = 월 정렬
    if to:
        stmt = stmt.where(Payslip.year_month <= to)
    result = await db.execute(stmt.order_by(Payslip.year_month.desc()))
    return list(result.scalars().all())


@router.get("", response_model=list[PayslipOut], dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def list_payslips(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    branch_id: str | None = Query(None, alias="branchId"),
    year_month: str | None = Query(None, alias="yearMonth"),
    employee_id: str | None = Query(None, alias="employeeId"),
    # `YYYY-MM` 범위 (양끝 포함) — 한 사람의 최근 몇 달을 한 번에 받을 때
    from_month: str | None = Query(None, alias="from"),
    to_month: str | None = Query(None, alias="to"),
    box: str | None = Query(None),
) -> list[Payslip]:
    stmt = select(Payslip)
    if employee_id:
        stmt = stmt.where(Payslip.employee_id == employee_id)
    if from_month:
        stmt = stmt.where(Payslip.year_month >= from_month)
    if to_month:
        stmt = stmt.where(Payslip.year_month <= to_month)
    # box=inbox → 결재 대기(SUBMITTED). box=decided → 처리 내역(승인/반려).
    if box == "inbox":
        stmt = stmt.where(Payslip.status == PayslipStatus.SUBMITTED)
    elif box == "decided":
        stmt = stmt.where(
            Payslip.status.in_([PayslipStatus.APPROVED, PayslipStatus.PAID, PayslipStatus.REJECTED])
        )
    # MANAGER는 항상 자기 지점만(box 유무와 무관), ADMIN은 전체
    if current.role not in (Role.MASTER, Role.ADMIN) and not branch_id:
        branch_id = current.branch_id
    if branch_id:
        stmt = stmt.join(Employee, Employee.id == Payslip.employee_id).where(
            Employee.branch_id == branch_id
        )
    if year_month:
        stmt = stmt.where(Payslip.year_month == year_month)
    result = await db.execute(stmt.order_by(Payslip.year_month.desc()))
    return list(result.scalars().all())


async def _decide(db: AsyncSession, payslip_id: str, actor: Employee) -> Payslip:
    payslip = await db.get(Payslip, payslip_id)
    if payslip is None:
        raise HTTPException(404, detail={"code": "PAYSLIP_NOT_FOUND", "message": "명세서를 찾을 수 없습니다"})
    if payslip.status != PayslipStatus.SUBMITTED:
        raise HTTPException(400, detail={"code": "NOT_SUBMITTED", "message": "제출된 명세서만 처리할 수 있어요"})
    if payslip.employee_id == actor.id:
        raise HTTPException(403, detail={"code": "SELF_DECIDE", "message": "본인 명세서는 본인이 결재할 수 없어요"})
    return payslip


@router.post("/{payslip_id}/approve", response_model=PayslipOut, dependencies=[Depends(require_role(Role.MASTER, Role.MANAGER))])
async def approve_payslip(
    payslip_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Payslip:
    payslip = await _decide(db, payslip_id, current)
    payslip.status = PayslipStatus.APPROVED
    payslip.decided_at = datetime.now(timezone.utc)
    payslip.decided_by_id = current.id
    await notify(db, employee_id=payslip.employee_id, **ntext.payslip_approved(payslip.year_month))
    await db.commit()
    await db.refresh(payslip)
    return payslip


@router.post("/{payslip_id}/reject", response_model=PayslipOut, dependencies=[Depends(require_role(Role.MASTER, Role.MANAGER))])
async def reject_payslip(
    payslip_id: str,
    payload: PayslipReject,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Payslip:
    payslip = await _decide(db, payslip_id, current)
    payslip.status = PayslipStatus.REJECTED
    payslip.reject_reason = payload.reason
    payslip.decided_at = datetime.now(timezone.utc)
    payslip.decided_by_id = current.id
    await notify(db, employee_id=payslip.employee_id, **ntext.payslip_rejected(payload.reason))
    await db.commit()
    await db.refresh(payslip)
    return payslip


@router.post("/{payslip_id}/pay", response_model=PayslipOut, dependencies=[Depends(require_role(Role.MASTER, Role.MANAGER))])
async def pay_payslip(
    payslip_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Payslip:
    """지급 처리 — 승인된 명세서를 실입금 확인 후 PAID 로. APPROVED 만 대상."""
    payslip = await db.get(Payslip, payslip_id)
    if payslip is None:
        raise HTTPException(404, detail={"code": "PAYSLIP_NOT_FOUND", "message": "명세서를 찾을 수 없습니다"})
    if payslip.status != PayslipStatus.APPROVED:
        raise HTTPException(400, detail={"code": "NOT_APPROVED", "message": "승인된 명세서만 지급 처리할 수 있어요"})
    payslip.status = PayslipStatus.PAID
    payslip.paid_at = datetime.now(timezone.utc)
    await notify(db, employee_id=payslip.employee_id, **ntext.payslip_paid(payslip.year_month))
    await db.commit()
    await db.refresh(payslip)
    return payslip
