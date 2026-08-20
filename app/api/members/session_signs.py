"""SessionSign 라우터 — CLAUDE.md §3.3.

POST [MEMBER]: 서명 저장 → usedSessions +1 → 만료 판정 → CLASS 점수 +2 적립.
반환 { sign, registration }.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_filter, get_current_user, require_role
from app.core.periods import period_range
from app.core.storage import save_signature
from app.enums import RegistrationStatus, RegistrationType, Role, ScoreCategory
from app.db.session import get_db
from app.models.staff.employee import Employee
from app.models.members.member import Member
from app.models.members.pt_survey import PtSurvey
from app.models.members.registration import Registration
from app.models.members.session_sign import SessionSign
from app.schemas.members.registration import RegistrationOut
from app.schemas.members.session_sign import SessionSignCreate, SessionSignOut, SessionSignResult
from app.services.scoring import accrue_score

CLASS_POINTS = 2  # 싸인 1건 = CLASS +2 (§4.6)

#: 몇 회차에 만족도 폼을 여나 (2026-08-20 요청)
#:
#: 10회 등록이 흔해서 **한참 남았을 때** 물어야 연장 이야기를 꺼낼 여지가 있다.
#: 마지막 회차에 물으면 이미 마음을 정한 뒤다.
PT_SURVEY_AT = 7

router = APIRouter(prefix="/session-signs", tags=["session-signs"])


async def _open_pt_survey(
    db: AsyncSession, registration: Registration, sign: SessionSign, trainer_id: str
) -> None:
    """신규 등록권의 7회차면 **만족도 폼을 하나 연다** (2026-08-20 요청).

    **신규만이다.** 재등록한 사람은 이미 겪어 보고 다시 온 것이라
    7회차에 "연장하실래요" 를 다시 묻는 것이 어색하다.

    **줄만 만들고 문자는 아직 안 보낸다.** 발신번호가 안 정해져서다
    (고민해볼꺼 21번) — 그때까지는 `GET /pt-surveys` 의 `url` 을 트레이너가
    복사해 직접 보낸다.

    받는 트레이너는 **그날 실제로 수업한 사람**이다. 등록권의 담당으로 하면
    대타로 들어간 날 물어본 것이 엉뚱한 사람에게 붙는다.
    """
    if registration.type != RegistrationType.NEW or sign.session_no != PT_SURVEY_AT:
        return
    # 되돌렸다 다시 찍는 일이 있어도 두 줄이 안 생긴다 (등록권당 하나다)
    exists = await db.scalar(
        select(PtSurvey.id).where(PtSurvey.registration_id == registration.id)
    )
    if exists is not None:
        return
    db.add(
        PtSurvey(
            registration_id=registration.id,
            member_id=registration.member_id,
            trainer_id=trainer_id,
            token=secrets.token_urlsafe(12),
            session_no=sign.session_no,
        )
    )


def _sign_out(
    sign: SessionSign, member_name: str | None, total_sessions: int | None, reg_type
) -> SessionSignOut:
    """SessionSignOut + 앱 기록 표시용 조인값(회원명·총 회차·신규/재등록)."""
    out = SessionSignOut.model_validate(sign)
    out.member_name = member_name
    out.total_sessions = total_sessions
    out.registration_type = reg_type
    return out


@router.post("", response_model=SessionSignResult, status_code=201)
async def create_session_sign(
    payload: SessionSignCreate,
    # 점장(MANAGER)도 트레이너로 수업함 → 싸인 허용. ADMIN·MASTER 는 운영 전담이라 제외.
    current: Employee = Depends(require_role(Role.MEMBER, Role.MANAGER)),
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
    await _open_pt_survey(db, registration, sign, performer_id)

    await db.commit()
    await db.refresh(sign)
    await db.refresh(registration)
    member = await db.get(Member, registration.member_id)
    return SessionSignResult(
        sign=_sign_out(sign, member.name if member else None, registration.total_sessions, registration.type),
        registration=RegistrationOut.model_validate(registration),
    )


@router.get("", response_model=list[SessionSignOut], dependencies=[Depends(get_current_user)])
async def list_session_signs(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_filter),  # ?branchId= 로 지점을 고를 수 있다
    trainer_id: str | None = Query(None, alias="trainerId"),
    member_id: str | None = Query(None, alias="memberId"),
    period: str | None = Query(None),
) -> list[SessionSignOut]:
    # 회원명·총 회차·신규/재등록을 함께 조인 → 앱이 별도 요청 없이 기록 한 줄을 그린다.
    stmt = (
        select(SessionSign, Member.name, Registration.total_sessions, Registration.type)
        .join(Member, Member.id == SessionSign.member_id)
        .join(Registration, Registration.id == SessionSign.registration_id)
    )
    if scope:
        stmt = stmt.join(Employee, Employee.id == SessionSign.performed_by_trainer_id).where(
            Employee.branch_id == scope
        )
    if trainer_id:
        stmt = stmt.where(SessionSign.performed_by_trainer_id == trainer_id)
    if member_id:
        stmt = stmt.where(SessionSign.member_id == member_id)
    if period:
        start, end = period_range(period)
        stmt = stmt.where(SessionSign.signed_at >= start, SessionSign.signed_at < end)
    rows = (await db.execute(stmt.order_by(SessionSign.signed_at.desc()))).all()
    return [_sign_out(sign, name, total, rtype) for sign, name, total, rtype in rows]
