"""Registration 라우터 — CLAUDE.md §3.2 (급여 인센 산출 입력값)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user
from app.core.periods import period_range
from app.db.session import get_db
from app.enums import RegistrationStatus, RegistrationType, Role
from app.models.org.employee import Employee
from app.models.sales.member import Member
from app.models.sales.registration import Registration
from app.schemas.sales.registration import RegistrationCreate, RegistrationOut

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
    if current.role != Role.ADMIN and trainer.branch_id != current.branch_id:
        raise HTTPException(403, detail={"code": "OTHER_BRANCH", "message": "다른 지점 등록은 생성할 수 없습니다"})
    registration = Registration(
        member_id=payload.member_id,
        trainer_id=payload.trainer_id,
        type=payload.type,
        total_sessions=payload.total_sessions,
        used_sessions=0,
        price_paid=payload.price_paid,
        session_unit_price=payload.session_unit_price,
        status=RegistrationStatus.ACTIVE,
        purchased_at=payload.purchased_at or datetime.now(timezone.utc),
    )
    db.add(registration)
    await db.commit()
    await db.refresh(registration)
    return registration
