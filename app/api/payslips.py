"""Payslip 라우터 — 급여명세서 산출·조회 (CLAUDE.md §5).

POST /generate [ADMIN]: 지점·월 대상 산출(재생성=교체). GET /me [SELF], GET [ADMIN,MANAGER].
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.periods import period_range
from app.db.session import get_db
from app.enums import EmployeeStatus, Role
from app.models.employee import Employee
from app.models.payslip import Payslip
from app.schemas.payslip import PayslipGenerateRequest, PayslipOut
from app.services.payroll import build_payslip_data, get_rank_policy

router = APIRouter(prefix="/payslips", tags=["payslips"])


@router.post("/generate", response_model=list[PayslipOut], dependencies=[Depends(require_role(Role.ADMIN))])
async def generate_payslips(
    payload: PayslipGenerateRequest, db: AsyncSession = Depends(get_db)
) -> list[Payslip]:
    start, _ = period_range(payload.year_month)
    employees = (
        await db.execute(
            select(Employee).where(
                Employee.branch_id == payload.branch_id,
                Employee.status == EmployeeStatus.ACTIVE,
                Employee.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    if employees:
        await db.execute(
            delete(Payslip).where(
                Payslip.year_month == payload.year_month,
                Payslip.employee_id.in_([e.id for e in employees]),
            )
        )

    generated: list[Payslip] = []
    for employee in employees:
        policy = await get_rank_policy(db, employee.rank, employee.branch_id, start)
        if policy is None:
            continue  # 요율 정책 없는 직급은 건너뜀
        data = await build_payslip_data(db, employee, payload.year_month, policy)
        payslip = Payslip(employee_id=employee.id, year_month=payload.year_month, **data)
        db.add(payslip)
        generated.append(payslip)

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


@router.get("", response_model=list[PayslipOut], dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def list_payslips(
    db: AsyncSession = Depends(get_db),
    branch_id: str | None = Query(None, alias="branchId"),
    year_month: str | None = Query(None, alias="yearMonth"),
) -> list[Payslip]:
    stmt = select(Payslip)
    if branch_id:
        stmt = stmt.join(Employee, Employee.id == Payslip.employee_id).where(
            Employee.branch_id == branch_id
        )
    if year_month:
        stmt = stmt.where(Payslip.year_month == year_month)
    result = await db.execute(stmt.order_by(Payslip.year_month.desc()))
    return list(result.scalars().all())
