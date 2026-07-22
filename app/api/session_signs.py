"""SessionSign 라우터 — CLAUDE.md §3.3.

POST [MEMBER]: 서명 저장 → usedSessions +1 → 만료 판정 → CLASS 점수 +2 적립.
반환 { sign, registration }.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.periods import period_range
from app.core.storage import save_signature
from app.enums import RegistrationStatus, Role, ScoreCategory
from app.db.session import get_db
from app.models.employee import Employee
from app.models.registration import Registration
from app.models.session_sign import SessionSign
from app.schemas.registration import RegistrationOut
from app.schemas.session_sign import SessionSignCreate, SessionSignOut, SessionSignResult
from app.services.scoring import accrue_score

CLASS_POINTS = 2  # 싸인 1건 = CLASS +2 (§4.6)

router = APIRouter(prefix="/session-signs", tags=["session-signs"])


@router.post("", response_model=SessionSignResult, status_code=201)
async def create_session_sign(
    payload: SessionSignCreate,
    current: Employee = Depends(require_role(Role.MEMBER)),
    db: AsyncSession = Depends(get_db),
) -> SessionSignResult:
    registration = await db.get(Registration, payload.registration_id)
    if registration is None:
        raise HTTPException(404, detail={"code": "REGISTRATION_NOT_FOUND", "message": "등록을 찾을 수 없습니다"})
    if registration.status == RegistrationStatus.EXPIRED or registration.used_sessions >= registration.total_sessions:
        raise HTTPException(400, detail={"code": "NO_SESSIONS_LEFT", "message": "남은 세션이 없습니다"})

    performer_id = payload.performed_by_trainer_id or current.id
    performer = current if performer_id == current.id else await db.get(Employee, performer_id)
    if performer is None:
        raise HTTPException(400, detail={"code": "TRAINER_NOT_FOUND", "message": "수행 트레이너가 존재하지 않습니다"})

    signature_url = save_signature(payload.signature_base64)
    sign = SessionSign(
        registration_id=registration.id,
        member_id=registration.member_id,
        performed_by_trainer_id=performer_id,
        session_no=registration.used_sessions + 1,
        signature_url=signature_url,
    )
    db.add(sign)
    await db.flush()  # sign.id 확보 (원천 기록 id)

    registration.used_sessions = sign.session_no
    if registration.used_sessions >= registration.total_sessions:
        registration.status = RegistrationStatus.EXPIRED

    await accrue_score(
        db,
        employee_id=performer_id,
        branch_id=performer.branch_id,
        category=ScoreCategory.CLASS,
        points=CLASS_POINTS,
        created_by_id=current.id,
        source_ref_id=sign.id,
        reason="세션 수행",
    )

    await db.commit()
    await db.refresh(sign)
    await db.refresh(registration)
    return SessionSignResult(
        sign=SessionSignOut.model_validate(sign),
        registration=RegistrationOut.model_validate(registration),
    )


@router.get("", response_model=list[SessionSignOut], dependencies=[Depends(get_current_user)])
async def list_session_signs(
    db: AsyncSession = Depends(get_db),
    trainer_id: str | None = Query(None, alias="trainerId"),
    member_id: str | None = Query(None, alias="memberId"),
    period: str | None = Query(None),
) -> list[SessionSign]:
    stmt = select(SessionSign)
    if trainer_id:
        stmt = stmt.where(SessionSign.performed_by_trainer_id == trainer_id)
    if member_id:
        stmt = stmt.where(SessionSign.member_id == member_id)
    if period:
        start, end = period_range(period)
        stmt = stmt.where(SessionSign.signed_at >= start, SessionSign.signed_at < end)
    result = await db.execute(stmt.order_by(SessionSign.signed_at.desc()))
    return list(result.scalars().all())
