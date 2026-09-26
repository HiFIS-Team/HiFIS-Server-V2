"""ContributionGrant 라우터 — 센터 기여도 지목 부여 (CLAUDE.md §4.4, [ADMIN,MANAGER])."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_filter, get_current_user, require_role
from app.core.periods import period_range
from app.db.session import get_db
from app.enums import ContribType, Role, ScoreCategory
from app.models.scoring.contribution import ContributionGrant
from app.models.staff.employee import Employee
from app.schemas.scoring.contribution import ContributionCreate, ContributionGrantOut
from app.services.scoring import accrue_score

# 최종 점수표: 창의적 아이디어 3 / 자발적 목표 업무 10(기본) / 근무 외 출근 1시간 이상 10(고정)
#
# **자발적 목표만 주는 사람이 고칠 수 있다** — 5~20 (2026-09-21 대표 요청).
# 여기 값은 안 고르고 보냈을 때의 기본값이다 (`ContributionCreate.points`).
FIXED_POINTS = {ContribType.IDEA: 3, ContribType.GOAL: 10, ContribType.EXTRA_WORK: 10}

#: 누가 누구에게 줄 수 있나 — **자기보다 아래에만** 준다
#:
#: 점장은 직원에게만, 대표·관리자는 점장·직원에게.
#: 위로 주거나 같은 급끼리 주고받는 길은 막는다 — 점장끼리 서로 얹어 주면
#: 랭킹이 뜻을 잃고, 본인에게 주는 것도 표에 자기 권한이 없어 막힌다.
GRANTABLE = {
    Role.MASTER: {Role.MANAGER, Role.MEMBER},
    Role.ADMIN: {Role.MANAGER, Role.MEMBER},
    Role.MANAGER: {Role.MEMBER},
}

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
    if employee.role not in GRANTABLE.get(current.role, set()):
        raise HTTPException(
            403,
            detail={"code": "NOT_GRANTABLE", "message": "이 직원에게는 기여도를 줄 수 없습니다"},
        )

    # 자발적 목표 업무만 **주는 사람이 5~20 중에서 고른다** (2026-09-21 대표 요청).
    # 안 고르면 예전처럼 10점이다 — 옛 앱은 이 칸을 안 보낸다.
    #
    # 다른 갈래에 실려 오면 **막는다.** 조용히 버리면 20점을 줬다고 생각한
    # 사람이 3점이 들어간 것을 모른다 (급여 커미션을 고칠 수 없는 직급이
    # 금액을 보냈을 때 400 을 내는 것과 같은 판단).
    if payload.points is not None and payload.type != ContribType.GOAL:
        raise HTTPException(
            400,
            detail={"code": "POINTS_FIXED", "message": "이 갈래는 점수가 정해져 있어요"},
        )
    points = payload.points or FIXED_POINTS[payload.type]
    # 근무 외 출근(1시간 이상)은 고정 10점. hours 는 기록용(옵션).
    hours = payload.hours if payload.type == ContribType.EXTRA_WORK else None

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
    scope: str | None = Depends(branch_filter),  # ?branchId= 로 지점을 고를 수 있다
    employee_id: str | None = Query(None, alias="employeeId"),
    # 준 사람으로 거르기 — 대표·관리자·점장의 '내가 준 기여 내역'이 쓴다.
    # 받은 사람(employeeId)과 **같이 주면 둘 다** 걸린다 (AND).
    granted_by_id: str | None = Query(None, alias="grantedById"),
    period: str | None = Query(None),  # "YYYY-MM" — 점수 원장과 동일. 앱 '이번 달 기여' 필터
) -> list[ContributionGrant]:
    stmt = select(ContributionGrant)
    if scope:
        stmt = stmt.join(Employee, Employee.id == ContributionGrant.employee_id).where(
            Employee.branch_id == scope
        )
    if employee_id:
        stmt = stmt.where(ContributionGrant.employee_id == employee_id)
    if granted_by_id:
        stmt = stmt.where(ContributionGrant.granted_by_id == granted_by_id)
    if period:
        start, end = period_range(period)
        stmt = stmt.where(ContributionGrant.created_at >= start, ContributionGrant.created_at < end)
    result = await db.execute(stmt.order_by(ContributionGrant.created_at.desc()))
    return list(result.scalars().all())
