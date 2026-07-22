"""Score 라우터 — 원장 조회 · 랭킹 · 요약 · 운영자 부여 (CLAUDE.md §4.1).

랭킹/진급 합산은 ScoreEvent 원장 하나에서 집계. period 는 저장 문자열("2026-07") 정확 일치.
TODO(스코프): 랭킹/목록을 요청자 소속 지점으로 제한 (§0).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user, require_role
from app.db.session import get_db
from app.enums import Role, ScoreCategory
from app.models.employee import Employee
from app.models.score_event import ScoreEvent
from app.schemas.score import RankingItem, ScoreCreate, ScoreEventOut, ScoreSummary
from app.services.scoring import accrue_score

router = APIRouter(prefix="/scores", tags=["scores"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ScoreEventOut])
async def list_scores(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    employee_id: str | None = Query(None, alias="employeeId"),
    category: ScoreCategory | None = Query(None),
    period: str | None = Query(None),
) -> list[ScoreEvent]:
    stmt = select(ScoreEvent)
    if scope:
        stmt = stmt.where(ScoreEvent.branch_id == scope)
    if employee_id:
        stmt = stmt.where(ScoreEvent.employee_id == employee_id)
    if category:
        stmt = stmt.where(ScoreEvent.category == category)
    if period:
        stmt = stmt.where(ScoreEvent.period == period)
    result = await db.execute(stmt.order_by(ScoreEvent.created_at.desc()))
    return list(result.scalars().all())


@router.get("/ranking", response_model=list[RankingItem])
async def ranking(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    category: ScoreCategory | None = Query(None),
    period: str | None = Query(None),
    branch_id: str | None = Query(None, alias="branchId"),
) -> list[RankingItem]:
    total = func.coalesce(func.sum(ScoreEvent.points), 0).label("points")
    stmt = select(Employee.id, Employee.name, total).join(
        ScoreEvent, ScoreEvent.employee_id == Employee.id
    )
    if scope:
        stmt = stmt.where(ScoreEvent.branch_id == scope)
    if category:
        stmt = stmt.where(ScoreEvent.category == category)
    if period:
        stmt = stmt.where(ScoreEvent.period == period)
    if branch_id:
        stmt = stmt.where(ScoreEvent.branch_id == branch_id)
    stmt = stmt.group_by(Employee.id, Employee.name).order_by(total.desc())
    rows = (await db.execute(stmt)).all()
    return [
        RankingItem(rank=i + 1, employee_id=row.id, name=row.name, points=row.points)
        for i, row in enumerate(rows)
    ]


@router.get("/summary", response_model=ScoreSummary)
async def summary(
    employee_id: str = Query(..., alias="employeeId"),
    period: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> ScoreSummary:
    stmt = select(ScoreEvent.category, func.coalesce(func.sum(ScoreEvent.points), 0)).where(
        ScoreEvent.employee_id == employee_id
    )
    if period:
        stmt = stmt.where(ScoreEvent.period == period)
    stmt = stmt.group_by(ScoreEvent.category)
    rows = (await db.execute(stmt)).all()

    by_category = {category.value: 0 for category in ScoreCategory}
    for category, points in rows:
        by_category[str(category)] = points
    return ScoreSummary(
        employee_id=employee_id, period=period, total=sum(by_category.values()), by_category=by_category
    )


@router.post("", response_model=ScoreEventOut, status_code=201)
async def create_score(
    payload: ScoreCreate,
    current: Employee = Depends(require_role(Role.ADMIN, Role.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ScoreEvent:
    employee = await db.get(Employee, payload.employee_id)
    if employee is None:
        raise HTTPException(400, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원이 존재하지 않습니다"})
    event = await accrue_score(
        db,
        employee_id=employee.id,
        branch_id=employee.branch_id,
        category=payload.category,
        points=payload.points,
        created_by_id=current.id,
        reason=payload.reason,
        period=payload.period,
    )
    await db.commit()
    await db.refresh(event)
    return event
