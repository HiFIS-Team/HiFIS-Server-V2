"""Event 라우터 — CLAUDE.md §6.8. 작성=인증, 수정/삭제=소유자/관리자."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import Role
from app.models.staff.employee import Employee
from app.models.board.event import Event
from app.schemas.board.event import EventCreate, EventOut, EventUpdate

router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(get_current_user)])


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "EVENT_NOT_FOUND", "message": "일정을 찾을 수 없습니다"})


async def _get_owned(event_id: str, current: Employee, db: AsyncSession) -> Event:
    event = await db.get(Event, event_id)
    if event is None:
        raise _not_found()
    if current.role not in (Role.MASTER, Role.ADMIN, Role.MANAGER) and event.owner_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "소유자만 수정할 수 있습니다"})
    return event


@router.get("", response_model=list[EventOut])
async def list_events(
    db: AsyncSession = Depends(get_db),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None, alias="to"),
    scope: str | None = Query(None),
) -> list[Event]:
    stmt = select(Event)
    if from_:
        stmt = stmt.where(Event.start_at >= from_)
    if to:
        stmt = stmt.where(Event.start_at <= to)
    if scope:
        stmt = stmt.where(Event.scope == scope)
    result = await db.execute(stmt.order_by(Event.start_at))
    return list(result.scalars().all())


@router.post("", response_model=EventOut, status_code=201)
async def create_event(
    payload: EventCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Event:
    event = Event(
        title=payload.title,
        start_at=payload.start_at,
        end_at=payload.end_at,
        category=payload.category,
        scope=payload.scope,
        color=payload.color,
        memo=payload.memo,
        owner_id=current.id,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@router.patch("/{event_id}", response_model=EventOut)
async def update_event(
    event_id: str,
    payload: EventUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Event:
    event = await _get_owned(event_id, current, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(event, key, value)
    await db.commit()
    await db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    event = await _get_owned(event_id, current, db)
    await db.delete(event)
    await db.commit()
    return None
