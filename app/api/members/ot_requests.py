"""OT 신청 관리 — 배정·수락·거절 (2026-09-28 대표 요청).

누가 무엇을 보는지는 `services/ot_requests.visible` 에 있다.
확정되면 공통 일정에 `000님 OT` 가 서고 신청자에게 문자가 간다.
"""

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.board.events import COMPANY_SCOPE
from app.core.deps import get_current_user
from app.core.periods import KST
from app.db.session import get_db
from app.enums import EventStatus, Gender, OtStatus
from app.models.board.event import Event
from app.models.members.ot_request import OtRequest
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.schemas.base import CamelModel
from app.services import notification_texts as ntext
from app.services.monthly_goals import today_kst
from app.services.notifications import notify
from app.services.ot_requests import _when, can_assign, can_take, sms_confirmed, visible

router = APIRouter(prefix="/ot-requests", tags=["ot-requests"])

#: 공통 일정의 종류·색 — 앱의 `수업` 과 같다 (종류는 글자로 주고받는다)
_EVENT_CATEGORY = "수업"
_EVENT_COLOR = "#00C471"


class OtRequestOut(CamelModel):
    id: str
    branch_id: str
    branch_name: str | None = None
    name: str
    gender: Gender
    age: int
    phone: str
    purpose: str
    visit_date: date
    start_time: time
    end_time: time
    status: OtStatus
    assignee_id: str | None = None
    assignee_name: str | None = None
    assigned_by_id: str | None = None
    created_at: datetime
    accepted_at: datetime | None = None
    converted_at: datetime | None = None


class OtAssign(CamelModel):
    assignee_id: str


class OtAccept(CamelModel):
    """수락 — 시간이 안 맞으면 고쳐서 낸다 (안 고쳤으면 신청한 값 그대로 온다)."""

    visit_date: date
    start_time: time
    end_time: time


async def _out(db: AsyncSession, rows: list[OtRequest]) -> list[OtRequestOut]:
    names = {
        e.id: e.name
        for e in await db.scalars(
            select(Employee).where(Employee.id.in_({r.assignee_id for r in rows if r.assignee_id}))
        )
    }
    branches = {
        b.id: b.name
        for b in await db.scalars(select(Branch).where(Branch.id.in_({r.branch_id for r in rows})))
    }
    out = []
    for r in rows:
        item = OtRequestOut.model_validate(r)
        item.assignee_name = names.get(r.assignee_id or "")
        item.branch_name = branches.get(r.branch_id)
        out.append(item)
    return out


async def _get(db: AsyncSession, ot_id: str, current: Employee) -> OtRequest:
    ot = await db.scalar(visible(select(OtRequest).where(OtRequest.id == ot_id), current))
    if ot is None:
        raise HTTPException(404, detail={"code": "OT_NOT_FOUND", "message": "OT 신청이 없어요"})
    return ot


@router.get("", response_model=list[OtRequestOut])
async def list_ot(
    status: OtStatus | None = Query(None),
    branch_id: str | None = Query(None, alias="branchId"),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OtRequestOut]:
    stmt = visible(select(OtRequest), current)
    if status:
        stmt = stmt.where(OtRequest.status == status)
    if branch_id:
        stmt = stmt.where(OtRequest.branch_id == branch_id)
    stmt = stmt.order_by(OtRequest.visit_date, OtRequest.start_time)
    return await _out(db, list(await db.scalars(stmt)))


@router.post("/{ot_id}/assign", response_model=OtRequestOut)
async def assign_ot(
    ot_id: str,
    payload: OtAssign,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OtRequestOut:
    ot = await _get(db, ot_id, current)
    if not can_assign(current, ot):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "권한이 없습니다"})
    if ot.status == OtStatus.ACCEPTED:
        raise HTTPException(400, detail={"code": "OT_DONE", "message": "이미 확정된 OT 예요"})
    assignee = await db.get(Employee, payload.assignee_id)
    if assignee is None or not can_take(current, assignee, ot):
        raise HTTPException(
            400, detail={"code": "BAD_ASSIGNEE", "message": "이 사람에게는 맡길 수 없어요"}
        )
    ot.assignee_id = assignee.id
    ot.assigned_by_id = current.id
    ot.assigned_at = datetime.now(timezone.utc)
    ot.status = OtStatus.ASSIGNED
    if assignee.id != current.id:
        await notify(db, employee_id=assignee.id, **ntext.ot_assigned(ot.name, _when(ot)))
    await db.commit()
    await db.refresh(ot)
    return (await _out(db, [ot]))[0]


@router.post("/{ot_id}/accept", response_model=OtRequestOut)
async def accept_ot(
    ot_id: str,
    payload: OtAccept,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OtRequestOut:
    """수락 — 공통 일정을 세우고 신청자에게 문자를 보낸다. **배정받은 본인만.**"""
    ot = await _get(db, ot_id, current)
    if ot.assignee_id != current.id or ot.status != OtStatus.ASSIGNED:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "권한이 없습니다"})
    if payload.visit_date < today_kst():
        raise HTTPException(
            400, detail={"code": "PAST_DATE", "message": "오늘 이후 날짜를 골라 주세요"}
        )
    if payload.end_time <= payload.start_time:
        raise HTTPException(
            400, detail={"code": "BAD_TIME", "message": "끝나는 시간이 시작보다 늦어야 해요"}
        )
    ot.visit_date = payload.visit_date
    ot.start_time = payload.start_time
    ot.end_time = payload.end_time

    event = Event(
        title=f"{ot.name}님 OT",
        start_at=datetime.combine(ot.visit_date, ot.start_time, KST),
        end_at=datetime.combine(ot.visit_date, ot.end_time, KST),
        all_day=False,
        category=_EVENT_CATEGORY,
        scope=COMPANY_SCOPE,
        color=_EVENT_COLOR,
        attendee_ids=[current.id],
        memo=f"담당 {current.name} · {ot.age}세 · {ot.purpose}",
        owner_id=current.id,
        status=EventStatus.APPROVED,
    )
    db.add(event)
    await db.flush()
    ot.event_id = event.id
    ot.status = OtStatus.ACCEPTED
    ot.accepted_at = datetime.now(timezone.utc)
    if ot.assigned_by_id and ot.assigned_by_id != current.id:
        await notify(
            db,
            employee_id=ot.assigned_by_id,
            **ntext.ot_accepted(ot.name, current.name, _when(ot)),
        )
    # **확정을 먼저 못 박는다** — 문자는 곁가지라 솔라피가 죽어도 확정은 남는다
    await db.commit()
    await sms_confirmed(db, ot, current)
    await db.commit()
    await db.refresh(ot)
    return (await _out(db, [ot]))[0]


@router.post("/{ot_id}/reject", response_model=OtRequestOut)
async def reject_ot(
    ot_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OtRequestOut:
    """거절 — **다시 미배정**으로 돌아간다. 배정한 사람에게 알린다."""
    ot = await _get(db, ot_id, current)
    if ot.assignee_id != current.id or ot.status != OtStatus.ASSIGNED:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "권한이 없습니다"})
    assigner = ot.assigned_by_id
    ot.assignee_id = None
    ot.assigned_by_id = None
    ot.assigned_at = None
    ot.status = OtStatus.PENDING
    if assigner and assigner != current.id:
        await notify(db, employee_id=assigner, **ntext.ot_rejected(ot.name, current.name))
    await db.commit()
    await db.refresh(ot)
    return (await _out(db, [ot]))[0]
