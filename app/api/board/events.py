"""Event 라우터 — CLAUDE.md §6.8. 작성=인증, 수정/삭제=소유자/관리자.

**MASTER·ADMIN 이 올린 일정만 바로 달력에 뜬다.** 나머지는 `PENDING` 으로
들어가 승인을 기다리고, 그동안 **올린 사람과 MASTER·ADMIN 에게만** 보인다.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import EventStatus, Role
from app.models.staff.employee import Employee
from app.models.board.event import Event
from app.schemas.board.event import EventCreate, EventOut, EventUpdate
from app.services.notifications import notify

router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(get_current_user)])


#: 승인 없이 올릴 수 있고, 남의 신청을 승인·반려하는 권한
_DECIDERS = (Role.MASTER, Role.ADMIN)


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
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None, alias="to"),
    scope: str | None = Query(None),
) -> list[Event]:
    # 반려된 일정은 아무에게도 안 보인다 — 행은 결재 이력으로 남기지만
    # 달력에 죽은 일정이 서면 칸만 어지럽힌다 (EventStatus 참고).
    # **이력은 `GET /me/inbox?status=REJECTED` 로 본다.**
    stmt = select(Event).where(Event.status != EventStatus.REJECTED)
    # 승인 대기는 올린 사람과 결재자에게만 — 남의 달력을 미리 어지럽히지 않는다
    if current.role not in _DECIDERS:
        stmt = stmt.where(
            or_(Event.status == EventStatus.APPROVED, Event.owner_id == current.id)
        )
    # 겹침(overlap): 여러 날 걸치는 일정도 창에 걸리면 포함 — end_at>=from AND start_at<=to
    if from_:
        stmt = stmt.where(Event.end_at >= from_)
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
        all_day=payload.all_day,
        category=payload.category,
        scope=payload.scope,
        color=payload.color,
        place=payload.place,
        attendee_ids=payload.attendee_ids,
        memo=payload.memo,
        owner_id=current.id,
        status=(
            EventStatus.APPROVED if current.role in _DECIDERS else EventStatus.PENDING
        ),
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
    # 승인받은 뒤 내용을 갈아치우면 승인의 뜻이 없다 — 결재자가 아니면 다시 대기로
    if current.role not in _DECIDERS:
        event.status = EventStatus.PENDING
    await db.commit()
    await db.refresh(event)
    return event


@router.post(
    "/{event_id}/approve",
    response_model=EventOut,
    dependencies=[Depends(require_role(Role.ADMIN))],  # MASTER 자동 승계
)
async def approve_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
) -> Event:
    """일정 신청 승인 — 이때부터 전 직원 달력에 뜬다."""
    event = await db.get(Event, event_id)
    if event is None:
        raise _not_found()
    if event.status != EventStatus.PENDING:
        raise HTTPException(
            400, detail={"code": "NOT_PENDING", "message": "대기 중인 일정이 아닙니다"}
        )
    event.status = EventStatus.APPROVED
    # 결재를 거쳤다는 표시 — 자동 승인(대표가 올린 것)과 가르는 자리다
    event.decided_at = datetime.now(timezone.utc)
    await notify(
        db,
        employee_id=event.owner_id,
        type="EVENT",
        title="일정이 승인됐어요",
        body=event.title,
        link=f"/schedule/{event.id}",
    )
    await db.commit()
    await db.refresh(event)
    return event


@router.post(
    "/{event_id}/reject",
    status_code=204,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def reject_event(
    event_id: str,
    reason: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> None:
    """일정 신청 반려 — **행은 남기고 달력에서만 뺀다.**

    예전에는 지웠다. 그러면 급여·월차·전자결재는 다 남는 반려 이력이
    **일정만 없어서**, 결재 화면 `반려` 칸에 일정이 한 건도 안 섰다.
    지금은 `REJECTED` 로 두고 `GET /events` 가 그걸 뺀다 — 달력은 그대로다.
    """
    event = await db.get(Event, event_id)
    if event is None:
        raise _not_found()
    if event.status != EventStatus.PENDING:
        raise HTTPException(
            400, detail={"code": "NOT_PENDING", "message": "대기 중인 일정이 아닙니다"}
        )
    event.status = EventStatus.REJECTED
    event.decided_at = datetime.now(timezone.utc)
    event.reject_reason = reason
    await notify(
        db,
        employee_id=event.owner_id,
        type="EVENT",
        title="일정이 반려됐어요",
        body=f"{event.title}{f' · {reason}' if reason else ''}",
        link="/schedule",
    )
    await db.commit()
    return None


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
