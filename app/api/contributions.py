"""ContributionGrant 라우터 — 센터 기여도 지목 부여 (CLAUDE.md §4.4, [ADMIN,MANAGER])."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user, require_role
from app.db.session import get_db
from app.enums import ContribType, Role, ScoreCategory
from app.models.contribution import ContributionGrant
from app.models.employee import Employee
from app.schemas.contribution import ContributionCreate, ContributionGrantOut
from app.services.scoring import accrue_score

FIXED_POINTS = {ContribType.IDEA: 5, ContribType.GOAL: 10}
EXTRA_WORK_RATE = 3

router = APIRouter(prefix="/contributions", tags=["contributions"])


@router.post("", response_model=ContributionGrantOut, status_code=201)
async def create_contribution(
    payload: ContributionCreate,
    current: Employee = Depends(require_role(Role.ADMIN, Role.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ContributionGrant:
    if payload.type == ContribType.SALES:
        raise HTTPException(400, detail={"code": "SALES_AUTO", "message": "매출성과는 자동 계산되어 직접 부여할 수 없습니다"})
    if not payload.reason.strip():
        raise HTTPException(400, detail={"code": "REASON_REQUIRED", "message": "부여 사유는 필수입니다"})
    employee = await db.get(Employee, payload.employee_id)
    if employee is None:
        raise HTTPException(400, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원이 존재하지 않습니다"})

    if payload.type == ContribType.EXTRA_WORK:
        if payload.hours is None:
            raise HTTPException(400, detail={"code": "HOURS_REQUIRED", "message": "추가근무는 hours 가 필요합니다"})
        points = payload.hours * EXTRA_WORK_RATE
        hours = payload.hours
    else:
        points = FIXED_POINTS[payload.type]
        hours = None

    grant = ContributionGrant(
        employee_id=payload.employee_id,
        type=payload.type,
        hours=hours,
        points=points,
        reason=payload.reason,
        granted_by_id=current.id,
    )
    db.add(grant)
    await db.flush()
    await accrue_score(
        db,
        employee_id=payload.employee_id,
        branch_id=employee.branch_id,
        category=ScoreCategory.CONTRIB,
        points=points,
        created_by_id=current.id,
        source_ref_id=grant.id,
        reason=payload.reason,
    )
    await db.commit()
    await db.refresh(grant)
    return grant


@router.get("", response_model=list[ContributionGrantOut], dependencies=[Depends(get_current_user)])
async def list_contributions(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    employee_id: str | None = Query(None, alias="employeeId"),
) -> list[ContributionGrant]:
    stmt = select(ContributionGrant)
    if scope:
        stmt = stmt.join(Employee, Employee.id == ContributionGrant.employee_id).where(
            Employee.branch_id == scope
        )
    if employee_id:
        stmt = stmt.where(ContributionGrant.employee_id == employee_id)
    result = await db.execute(stmt.order_by(ContributionGrant.created_at.desc()))
    return list(result.scalars().all())
