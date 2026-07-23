"""이모지 반응 라우터 — 공지·회의록·채팅 공통 토글 (CLAUDE.md §6.12)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import ReactionTargetType
from app.models.org.employee import Employee
from app.schemas.collab.reaction import ReactionAgg, ReactionToggle, ToggleResult
from app.services.reactions import aggregate_one, toggle_reaction

router = APIRouter(prefix="/reactions", tags=["reactions"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ReactionAgg])
async def list_reactions(
    target_type: ReactionTargetType = Query(..., alias="targetType"),
    target_id: str = Query(..., alias="targetId"),
    db: AsyncSession = Depends(get_db),
) -> list[ReactionAgg]:
    return await aggregate_one(db, target_type, target_id)


@router.post("", response_model=ToggleResult)
async def toggle(
    payload: ReactionToggle,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ToggleResult:
    added = await toggle_reaction(
        db,
        target_type=payload.target_type,
        target_id=payload.target_id,
        emoji=payload.emoji,
        employee_id=current.id,
    )
    await db.commit()
    reactions = await aggregate_one(db, payload.target_type, payload.target_id)
    return ToggleResult(added=added, reactions=reactions)
