"""이모지 반응 라우터 — 공지·회의록·채팅 공통 토글 (CLAUDE.md §6.12)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import ReactionTargetType
from app.models.chat.chat import Message
from app.models.projects.meeting import Meeting
from app.models.staff.employee import Employee
from app.schemas.board.reaction import ReactionAgg, ReactionToggle, ToggleResult
from app.services.chat import is_member
from app.services.reactions import aggregate_one, toggle_reaction
from app.services.notice_visibility import is_notice_blocked
from app.models.board.notice import Notice

router = APIRouter(prefix="/reactions", tags=["reactions"], dependencies=[Depends(get_current_user)])


async def _check_target_access(
    db: AsyncSession, target_type: ReactionTargetType, target_id: str, current: Employee
) -> None:
    """대상마다 볼 수 있는 사람만 — 공지는 공용이라 검사가 없다."""
    if target_type is ReactionTargetType.NOTICE:
        if await db.get(Notice, target_id) is None or await is_notice_blocked(db, current):
            raise HTTPException(404, detail={"code": "NOTICE_NOT_FOUND", "message": "공지를 찾을 수 없습니다"})
        return
    if target_type is ReactionTargetType.PROJECT:
        from app.api.projects.projects import _ensure_visible, _get_project_or_404

        project = await _get_project_or_404(db, target_id)
        await _ensure_visible(db, project, current)
        return
    if target_type is ReactionTargetType.MEETING:
        from app.api.projects.meetings import _can_view

        meeting = await db.get(Meeting, target_id)
        if meeting is None:
            raise HTTPException(404, detail={"code": "MEETING_NOT_FOUND", "message": "회의록을 찾을 수 없습니다"})
        if not await _can_view(db, meeting, current):
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "이 회의록을 볼 권한이 없습니다"})
        return
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
