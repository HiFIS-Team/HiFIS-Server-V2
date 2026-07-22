"""Score 라우터 (조회) — CLAUDE.md §4.1.

이번 단계는 원장 조회만. ranking/summary/운영자 POST 는 Phase 3 점수 엔진에서.
period 는 저장된 문자열("2026-07")과 정확 일치.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import ScoreCategory
from app.models.score_event import ScoreEvent
from app.schemas.score import ScoreEventOut

router = APIRouter(prefix="/scores", tags=["scores"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ScoreEventOut])
async def list_scores(
    db: AsyncSession = Depends(get_db),
    employee_id: str | None = Query(None, alias="employeeId"),
    category: ScoreCategory | None = Query(None),
    period: str | None = Query(None),
) -> list[ScoreEvent]:
    stmt = select(ScoreEvent)
    if employee_id:
        stmt = stmt.where(ScoreEvent.employee_id == employee_id)
    if category:
        stmt = stmt.where(ScoreEvent.category == category)
    if period:
        stmt = stmt.where(ScoreEvent.period == period)
    result = await db.execute(stmt.order_by(ScoreEvent.created_at.desc()))
    return list(result.scalars().all())
