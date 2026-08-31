"""Registration 라우터 — CLAUDE.md §3.2 (급여 인센 산출 입력값)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user
from app.core.periods import period_range
from app.db.session import get_db
from app.enums import RegistrationType, Role
from app.models.staff.employee import Employee
from app.models.members.member import Member
from app.models.members.registration import Registration
from app.schemas.members.registration import RegistrationCreate, RegistrationOut
from app.services.registrations import accrue_sales_score, ensure_used_within, initial_status

router = APIRouter(
    prefix="/registrations", tags=["registrations"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=list[RegistrationOut])
async def list_registrations(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    trainer_id: str | None = Query(None, alias="trainerId"),
    reg_type: RegistrationType | None = Query(None, alias="type"),
    period: str | None = Query(None),
) -> list[Registration]:
    stmt = select(Registration)
    if scope:
        stmt = stmt.join(Employee, Employee.id == Registration.trainer_id).where(
            Employee.branch_id == scope
        )
    if trainer_id:
        stmt = stmt.where(Registration.trainer_id == trainer_id)
    if reg_type:
        stmt = stmt.where(Registration.type == reg_type)
    if period:
        start, end = period_range(period)
        stmt = stmt.where(Registration.purchased_at >= start, Registration.purchased_at < end)
    result = await db.execute(stmt.order_by(Registration.purchased_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=RegistrationOut, status_code=201)
async def create_registration(
    payload: RegistrationCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Registration:
    if await db.get(Member, payload.member_id) is None:
        raise HTTPException(400, detail={"code": "MEMBER_NOT_FOUND", "message": "회원이 존재하지 않습니다"})
    trainer = await db.get(Employee, payload.trainer_id)
    if trainer is None:
        raise HTTPException(400, detail={"code": "TRAINER_NOT_FOUND", "message": "트레이너가 존재하지 않습니다"})
    # 급여 조작 방지: MEMBER 는 본인 담당(trainer=self)만 / 크로스브랜치 등록 차단(ADMIN 제외)
    if current.role == Role.MEMBER and payload.trainer_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 담당 등록만 생성할 수 있습니다"})
    if current.role not in (Role.MASTER, Role.ADMIN) and trainer.branch_id != current.branch_id:
        raise HTTPException(403, detail={"code": "OTHER_BRANCH", "message": "다른 지점 등록은 생성할 수 없습니다"})
    # 기존 회원의 지난 등록권을 뒤늦게 넣을 수 있다 — 이미 받은 회차를 그대로
    # 담고, 다 썼으면 처음부터 만료다 (`services/registrations.py`)
    ensure_used_within(payload.used_sessions, payload.total_sessions)
    registration = Registration(
        member_id=payload.member_id,
        trainer_id=payload.trainer_id,
        type=payload.type,
        total_sessions=payload.total_sessions,
        used_sessions=payload.used_sessions,
        price_paid=payload.price_paid,
        session_unit_price=payload.session_unit_price,
        status=initial_status(payload.used_sessions, payload.total_sessions),
        purchased_at=payload.purchased_at or datetime.now(timezone.utc),
    )
    db.add(registration)
    await db.flush()  # 점수의 source_ref_id 에 쓸 등록권 id 를 먼저 얻는다
    await accrue_sales_score(db, registration, trainer)
    await db.commit()
    await db.refresh(registration)
    return registration
