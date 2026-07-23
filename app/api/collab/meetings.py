"""Meeting 라우터 — CLAUDE.md §6.3. 작성=인증, 수정/삭제=작성자/관리자."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import MeetingScope, ReactionTargetType, Role
from app.models.org.employee import Employee
from app.models.collab.meeting import Meeting
from app.models.collab.project import Project
from app.models.collab.reaction import Reaction
from app.schemas.collab.meeting import MeetingCreate, MeetingOut, MeetingUpdate
from app.services.reactions import aggregate_for

router = APIRouter(prefix="/meetings", tags=["meetings"], dependencies=[Depends(get_current_user)])


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "MEETING_NOT_FOUND", "message": "회의록을 찾을 수 없습니다"})


async def _to_out(db: AsyncSession, meetings: list[Meeting]) -> list[MeetingOut]:
    agg = await aggregate_for(db, ReactionTargetType.MEETING, [m.id for m in meetings])
    out = []
    for m in meetings:
        model = MeetingOut.model_validate(m)
        model.reactions = agg[m.id]
        out.append(model)
    return out


async def _get_owned(meeting_id: str, current: Employee, db: AsyncSession) -> Meeting:
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise _not_found()
    if current.role not in (Role.ADMIN, Role.MANAGER) and meeting.author_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "작성자만 수정할 수 있습니다"})
    return meeting


@router.get("", response_model=list[MeetingOut])
async def list_meetings(
    db: AsyncSession = Depends(get_db),
    scope: MeetingScope | None = Query(None),
    q: str | None = Query(None),
    sort: str | None = Query(None),
) -> list[MeetingOut]:
    stmt = select(Meeting)
    if scope:
        stmt = stmt.where(Meeting.scope == scope)
    if q:
        stmt = stmt.where(Meeting.title.ilike(f"%{q}%"))
    order = Meeting.meeting_at.asc() if sort == "meetingAt" else Meeting.meeting_at.desc()
    result = await db.execute(stmt.order_by(order))
    return await _to_out(db, list(result.scalars().all()))


@router.post("", response_model=MeetingOut, status_code=201)
async def create_meeting(
    payload: MeetingCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeetingOut:
    if payload.project_id is not None and await db.get(Project, payload.project_id) is None:
        raise HTTPException(400, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트가 존재하지 않습니다"})
    meeting = Meeting(
        title=payload.title,
        blocks=payload.blocks,
        scope=payload.scope,
        attendee_ids=payload.attendee_ids,
        project_id=payload.project_id,
        author_id=current.id,
        meeting_at=payload.meeting_at,
    )
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    return (await _to_out(db, [meeting]))[0]


@router.get("/{meeting_id}", response_model=MeetingOut)
async def get_meeting(meeting_id: str, db: AsyncSession = Depends(get_db)) -> MeetingOut:
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise _not_found()
    return (await _to_out(db, [meeting]))[0]


@router.patch("/{meeting_id}", response_model=MeetingOut)
async def update_meeting(
    meeting_id: str,
    payload: MeetingUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeetingOut:
    meeting = await _get_owned(meeting_id, current, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(meeting, key, value)
    await db.commit()
    await db.refresh(meeting)
    return (await _to_out(db, [meeting]))[0]


@router.delete("/{meeting_id}", status_code=204)
async def delete_meeting(
    meeting_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    meeting = await _get_owned(meeting_id, current, db)
    await db.execute(
        delete(Reaction).where(
            Reaction.target_type == ReactionTargetType.MEETING,
            Reaction.target_id == meeting_id,
        )
    )
    await db.delete(meeting)
    await db.commit()
    return None
