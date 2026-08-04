"""Score 라우터 — 원장 조회 · 랭킹 · 요약 · 운영자 부여 (CLAUDE.md §4.1).

랭킹/진급 합산은 ScoreEvent 원장 하나에서 집계. period 는 저장 문자열("2026-07") 정확 일치.
랭킹/목록은 지점 스코프(§0): MEMBER=본인 지점 / MANAGER·ADMIN=전체.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user, require_role
from app.core.periods import current_period
from app.db.session import get_db
from app.enums import RankingKind, Role, ScoreCategory
from app.models.staff.employee import Employee
from app.models.scoring.score_event import ScoreEvent
from app.schemas.scoring.score import (
    RankingBoardItem,
    RankingItem,
    ScoreCreate,
    ScoreEventOut,
    ScoreSummary,
)
from app.services.ranking import kind_conditions
from app.services.ranking_board import METRICS, build_board, rank_board
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
    kind: RankingKind | None = Query(None),
    category: ScoreCategory | None = Query(None),
    period: str | None = Query(None),
    branch_id: str | None = Query(None, alias="branchId"),
) -> list[RankingItem]:
    # 랭킹은 '전사 통합'(전 지점) — 전 인원을 한 줄로 세운다(멤버·매니저 모두 동일한 통합 랭킹).
    # 특정 지점 랭킹만 보려면 branchId 로 필터. (지점 스코프를 걸지 않는 이유: §branch_scope 주석)
    total = func.coalesce(func.sum(ScoreEvent.points), 0).label("points")
    stmt = select(Employee.id, Employee.name, total).join(
        ScoreEvent, ScoreEvent.employee_id == Employee.id
    )
    # kind(랭킹 탭)가 category 보다 우선. OVERALL=필터 없음, SALES=CONTRIB 중 sales:* 만.
    if kind is not None:
        stmt = stmt.where(*kind_conditions(kind))
    elif category is not None:
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


@router.get("/ranking/board", response_model=list[RankingBoardItem])
async def ranking_board(
    db: AsyncSession = Depends(get_db),
    period: str | None = Query(None, description="YYYY-MM (없으면 이번 달)"),
    branch_id: str | None = Query(None, alias="branchId"),
) -> list[RankingBoardItem]:
    """랭킹 화면 한 판 — 사람마다 항목별 값과 **지난달 순위**를 같이 준다.

    `/scores/ranking` 은 kind 별 점수 합만 주는데, 앱 화면은 "신규 3 · 재등록 5"
    같은 근거 줄과 지난달 대비 변동을 같이 보여준다. 그 값들이 등록권·설문·
    환경정비·프로젝트에 흩어져 있어 여기서 한 번에 모은다.

    순위는 **앱이 매긴다** — 지점 필터를 바꿀 때마다 다시 요청하지 않게.
    """
    period = period or current_period()
    board = await build_board(db, period=period, branch_id=branch_id)

    # 지난달 순위 — 같은 방식으로 지난달 판을 만들어 등수만 뽑는다
    year, month = (int(x) for x in period.split("-"))
    before = f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"
    last = await build_board(db, period=before, branch_id=branch_id)
    ranks = rank_board(last)
    for row in board:
        row["lastRank"] = ranks.get(row["employeeId"], [0] * len(METRICS))

    return [RankingBoardItem.model_validate(row) for row in board]


@router.get("/summary", response_model=ScoreSummary)
async def summary(
    employee_id: str = Query(..., alias="employeeId"),
    period: str | None = Query(None),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScoreSummary:
    if current.role == Role.MEMBER and employee_id != current.id:  # 멤버는 본인 요약만
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 점수만 조회할 수 있습니다"})
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
