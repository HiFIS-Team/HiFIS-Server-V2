"""이모지 반응 라우터 — 공지·회의록·채팅 공통 토글 (CLAUDE.md §6.12)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import ReactionTargetType
from app.models.chat.chat import Message
from app.models.staff.employee import Employee
from app.schemas.board.reaction import ReactionAgg, ReactionToggle, ToggleResult
from app.services.chat import is_member
from app.services.reactions import aggregate_one, toggle_reaction

router = APIRouter(prefix="/reactions", tags=["reactions"], dependencies=[Depends(get_current_user)])


async def _check_target_access(
    db: AsyncSession, target_type: ReactionTargetType, target_id: str, current: Employee
) -> None:
    """MESSAGE 반응은 그 방 멤버만(공지·회의록은 공용이라 제한 없음)."""
    if target_type != ReactionTargetType.MESSAGE:
        return
    message = await db.get(Message, target_id)
    if message is None:
        raise HTTPException(404, detail={"code": "MESSAGE_NOT_FOUND", "message": "메시지를 찾을 수 없습니다"})
    if not await is_member(db, message.room_id, current.id):
        raise HTTPException(403, detail={"code": "NOT_ROOM_MEMBER", "message": "이 방의 멤버가 아닙니다"})


@router.get("", response_model=list[ReactionAgg])
async def list_reactions(
    target_type: ReactionTargetType = Query(..., alias="targetType"),
    target_id: str = Query(..., alias="targetId"),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReactionAgg]:
    await _check_target_access(db, target_type, target_id, current)
    return await aggregate_one(db, target_type, target_id)


@router.post("", response_model=ToggleResult)
async def toggle(
    payload: ReactionToggle,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ToggleResult:
    await _check_target_access(db, payload.target_type, payload.target_id, current)
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
