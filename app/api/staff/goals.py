"""이달의 목표 — 적기(MANAGER·MEMBER)와 모아 보기(MASTER·ADMIN) (2026-09-28 대표 요청).

**본인과 대표·관리자만 본다.** 같은 지점 점장에게도 안 연다 (2026-09-28 결정).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import Role
from app.models.staff.employee import Employee
from app.models.staff.monthly_goal import MonthlyGoal
from app.schemas.base import CamelModel
from app.services.monthly_goals import (
    GOAL_MAX_ITEMS,
    GOAL_MAX_LEN,
    GOAL_MIN_ITEMS,
    first_monday,
    goal_of,
    today_kst,
    writes_goal,
    year_month,
)

router = APIRouter(prefix="/goals", tags=["goals"])


class MonthlyGoalOut(CamelModel):
    id: str
    employee_id: str
    year_month: str
    items: list[str]
    created_at: datetime


class MyGoalOut(CamelModel):
    #: 이번 달 (`YYYY-MM`, KST)
    year_month: str
    #: 적는 사람인가 — 대표·관리자는 false
    writes: bool
    #: 지금 재촉할 때인가 — 첫 월요일이 지났고 아직 안 적었다 (앱 모달이 본다)
    due: bool
    goal: MonthlyGoalOut | None = None


class GoalSubmit(CamelModel):
    items: list[str] = Field(max_length=GOAL_MAX_ITEMS)


@router.get("/me", response_model=MyGoalOut)
async def my_goal(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyGoalOut:
    today = today_kst()
    ym = year_month(today)
    writes = writes_goal(current)
    goal = await goal_of(db, current.id, ym) if writes else None
    return MyGoalOut(
        year_month=ym,
        writes=writes,
        due=writes and goal is None and today >= first_monday(today),
        goal=goal,
    )


@router.get("/me/list", response_model=list[MonthlyGoalOut])
async def my_goals(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MonthlyGoal]:
    """내가 낸 목표 전부 — 최신 달이 먼저. 지난 달 것을 다시 볼 자리다."""
    return list(
        await db.scalars(
            select(MonthlyGoal)
            .where(MonthlyGoal.employee_id == current.id)
            .order_by(MonthlyGoal.year_month.desc())
        )
    )


@router.post("/me", response_model=MonthlyGoalOut, status_code=201)
async def submit_goal(
    payload: GoalSubmit,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonthlyGoal:
    """이번 달 목표 내기 — **한 번 내면 잠긴다** (고치는 길이 없다)."""
    if not writes_goal(current):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "권한이 없습니다"})
    items = [item.strip() for item in payload.items if item.strip()]
    if len(items) < GOAL_MIN_ITEMS:
        raise HTTPException(
            400,
            detail={"code": "GOAL_TOO_FEW", "message": f"목표를 {GOAL_MIN_ITEMS}개 이상 적어 주세요"},
        )
    if any(len(item) > GOAL_MAX_LEN for item in items):
        raise HTTPException(
            400,
            detail={"code": "GOAL_TOO_LONG", "message": f"목표 한 줄은 {GOAL_MAX_LEN}자까지예요"},
        )
    goal = MonthlyGoal(employee_id=current.id, year_month=year_month(today_kst()), items=items)
    db.add(goal)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            409, detail={"code": "GOAL_LOCKED", "message": "이번 달 목표는 이미 냈어요"}
        )
    await db.refresh(goal)
    return goal


@router.get("", response_model=list[MonthlyGoalOut])
async def list_goals(
    ym: str = Query(..., alias="yearMonth", pattern=r"^\d{4}-\d{2}$"),
    _: Employee = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> list[MonthlyGoal]:
    """그 달 전 직원 목표 — MASTER·ADMIN 만. 사람 명단은 앱이 이미 들고 있다."""
    return list(await db.scalars(select(MonthlyGoal).where(MonthlyGoal.year_month == ym)))
