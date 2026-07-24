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
from app.enums import PayslipStatus, Role
from app.models.org.employee import Employee
from app.models.payroll.payslip import Payslip
from app.schemas.payroll.payslip import (
    PaydayWindowOut,
    PayslipGenerateRequest,
    PayslipOut,
    PayslipReject,
    PayslipSubmit,
)
from app.services import notification_texts as ntext
from app.services.notifications import notify
from app.services.payroll import (
    build_payslip_data,
    generate_branch_payslips,
    get_rank_policy,
    payday_window,
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
) -> PaydayWindowOut:
    """급여 신청 창(지급일 여부). 지급일 당일만 신청 가능."""
    return PaydayWindowOut(**payday_window(year_month, date.today()))


@router.post("/me/submit", response_model=PayslipOut)
async def submit_my_payslip(
    payload: PayslipSubmit,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Payslip:
    """본인 급여 신청(제출). 지급일 당일만 가능 → DRAFT/REJECTED → SUBMITTED. 명세서 없으면 즉석 산출."""
    if not payday_window(payload.year_month, date.today())["is_open"]:
        raise HTTPException(403, detail={"code": "NOT_PAYDAY", "message": "급여 지급일에만 신청할 수 있어요"})
    payslip = (
        await db.execute(
            select(Payslip).where(
                Payslip.employee_id == current.id, Payslip.year_month == payload.year_month
            )
        )
    ).scalar_one_or_none()
    if payslip is None:
        start, _ = period_range(payload.year_month)
        policy = await get_rank_policy(db, current.rank, current.branch_id, start)
        if policy is None:
            raise HTTPException(400, detail={"code": "NO_RANK_POLICY", "message": "직급 급여 정책이 없어 신청할 수 없어요"})
        data = await build_payslip_data(db, current, payload.year_month, policy)
        payslip = Payslip(employee_id=current.id, year_month=payload.year_month, **data)
        db.add(payslip)
        await db.flush()
    if payslip.status in (PayslipStatus.SUBMITTED, PayslipStatus.APPROVED):
        raise HTTPException(400, detail={"code": "ALREADY_SUBMITTED", "message": "이미 제출된 명세서예요"})
    payslip.status = PayslipStatus.SUBMITTED
    payslip.submitted_at = datetime.now(timezone.utc)
    payslip.reject_reason = None
    payslip.decided_at = None
    payslip.decided_by_id = None
    await db.commit()
    await db.refresh(payslip)
    return payslip


@router.get("", response_model=list[PayslipOut], dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def list_payslips(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    branch_id: str | None = Query(None, alias="branchId"),
    year_month: str | None = Query(None, alias="yearMonth"),
    box: str | None = Query(None),
) -> list[Payslip]:
    stmt = select(Payslip)
    # box=inbox → 결재 대기(SUBMITTED). box=decided → 처리 내역(승인/반려).
    if box == "inbox":
        stmt = stmt.where(Payslip.status == PayslipStatus.SUBMITTED)
    elif box == "decided":
        stmt = stmt.where(Payslip.status.in_([PayslipStatus.APPROVED, PayslipStatus.REJECTED]))
    # MANAGER는 항상 자기 지점만(box 유무와 무관), ADMIN은 전체
    if current.role != Role.ADMIN and not branch_id:
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


@router.post("/{payslip_id}/approve", response_model=PayslipOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
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


@router.post("/{payslip_id}/reject", response_model=PayslipOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
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
