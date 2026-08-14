"""Meeting 라우터 — CLAUDE.md §6.3. 작성=인증, 수정/삭제=작성자/관리자."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import MeetingScope, ReactionTargetType, Role
from app.models.staff.employee import Employee
from app.models.projects.meeting import Meeting
from app.models.projects.project import Project
from app.models.board.reaction import Reaction
from app.schemas.projects.meeting import MeetingCreate, MeetingOut, MeetingUpdate
from app.services import notification_texts as ntext
from app.services.notifications import notify_bosses
from app.services.reactions import aggregate_for

router = APIRouter(prefix="/meetings", tags=["meetings"], dependencies=[Depends(get_current_user)])


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "MEETING_NOT_FOUND", "message": "회의록을 찾을 수 없습니다"})


def _visible_filter(current: Employee):
    """목록 가시성 — **`PEOPLE` 만 가린다** (2026-08-14 대표 결정).

    예전에는 `PROJECT` 회의록을 **그 프로젝트 담당자에게만** 보여줬다.
    그런데 담당자·참석자는 **누가 하느냐를 지정하는 값이지 볼 권한이 아니다** —
    프로젝트 자체도 전 직원이 다 본다(`list_projects` 에 필터가 없다).
    회의록을 프로젝트에 거는 순간 전 직원이 보던 글이 사라지는 것이 그 증거였다.

    `PEOPLE` 만 남긴 이유: 그건 담당이 아니라 **쓰는 사람이 고른 비공개**다.
    면담·인사 이야기가 들어가는 자리라 작성자·참석자만 본다.
    """
    if current.role in (Role.MASTER, Role.ADMIN):
        return None  # 필터 없음 = 전부
    return or_(
        Meeting.scope != MeetingScope.PEOPLE,
        Meeting.author_id == current.id,
        Meeting.attendee_ids.contains([current.id]),
    )


async def _can_view(db: AsyncSession, meeting: Meeting, current: Employee) -> bool:
    if current.role in (Role.MASTER, Role.ADMIN):
        return True
    if meeting.author_id == current.id or current.id in (meeting.attendee_ids or []):
        return True
    # 목록과 같은 규칙 — 갈리면 목록에 뜬 줄을 눌렀는데 403 이 난다
    return meeting.scope != MeetingScope.PEOPLE


def _forbidden_view() -> HTTPException:
    return HTTPException(403, detail={"code": "FORBIDDEN", "message": "이 회의록을 볼 권한이 없습니다"})


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
    if not await _can_view(db, meeting, current):
        raise _forbidden_view()  # 못 보는 회의록은 수정·삭제도 불가
    if current.role not in (Role.MASTER, Role.ADMIN, Role.MANAGER) and meeting.author_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "작성자만 수정할 수 있습니다"})
    return meeting


@router.get("", response_model=list[MeetingOut])
async def list_meetings(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    scope: MeetingScope | None = Query(None),
    q: str | None = Query(None),
    sort: str | None = Query(None),
) -> list[MeetingOut]:
    stmt = select(Meeting)
    visible = _visible_filter(current)
    if visible is not None:
        stmt = stmt.where(visible)
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
    await db.flush()  # id 가 있어야 알림 링크를 만든다
    # 대표·관리자에게 알린다 (2026-08-11 대표 요청).
    # **공개 범위(scope)를 안 본다** — 못 보는 회의록이면 눌렀을 때 403 이지만,
    # MASTER·ADMIN 은 `_can_view` 가 전부 통과시켜서 그럴 일이 없다.
    await notify_bosses(
        db, exclude=current.id, **ntext.meeting_created(meeting.title, current.name, meeting.id)
    )
    await db.commit()
    await db.refresh(meeting)
    return (await _to_out(db, [meeting]))[0]


@router.get("/{meeting_id}", response_model=MeetingOut)
async def get_meeting(
    meeting_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeetingOut:
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise _not_found()
    if not await _can_view(db, meeting, current):
        raise _forbidden_view()
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
