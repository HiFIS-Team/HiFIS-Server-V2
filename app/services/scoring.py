"""점수 적립 서비스 — 모든 점수는 ScoreEvent 원장 하나로 (CLAUDE.md §4).

commit 은 호출자가 담당 (트랜잭션 경계 유지).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import current_period
from app.enums import ScoreCategory
from app.models.scoring.score_event import ScoreEvent


async def accrue_score(
    db: AsyncSession,
    *,
    employee_id: str,
    branch_id: str,
    category: ScoreCategory,
    points: int,
    created_by_id: str | None = None,  # 시스템 발생(웹훅/스케줄러)이면 None
    source_ref_id: str | None = None,
    reason: str | None = None,
    period: str | None = None,
) -> ScoreEvent:
    event = ScoreEvent(
        employee_id=employee_id,
        branch_id=branch_id,
        category=category,
        points=points,
        reason=reason,
        source_ref_id=source_ref_id,
        period=period or current_period(),
        created_by_id=created_by_id,
    )
    db.add(event)
    return event
