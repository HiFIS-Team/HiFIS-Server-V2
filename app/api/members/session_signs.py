"""SessionSign 라우터 — CLAUDE.md §3.3.

POST [MEMBER]: 서명 저장 → usedSessions +1 → 만료 판정 → CLASS 점수 +2 적립.
반환 { sign, registration }.
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.deps import branch_filter, get_current_user, require_role
from app.core.periods import period_range
from app.core.tokens import public_token
from app.core.storage import save_signature
from app.enums import RegistrationStatus, RegistrationType, Role, ScoreCategory, WorkoutKind
from app.db.session import get_db
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.models.members.member import Member
from app.models.members.pt_survey import PtSurvey
from app.models.members.registration import Registration
from app.models.members.session_sign import SessionSign
from app.models.members.workout import WorkoutLog
from app.schemas.members.registration import RegistrationOut
from app.schemas.members.session_sign import SessionSignCreate, SessionSignOut, SessionSignResult
from app.services import sms
from app.services.scoring import accrue_score

CLASS_POINTS = 2  # 싸인 1건 = CLASS +2 (§4.6)

#: 몇 회차에 만족도 폼을 여나 (2026-08-20 요청)
#:
#: 10회 등록이 흔해서 **한참 남았을 때** 물어야 연장 이야기를 꺼낼 여지가 있다.
#: 마지막 회차에 물으면 이미 마음을 정한 뒤다.
PT_SURVEY_AT = 7

logger = logging.getLogger("app.pt_survey")

#: LMS 제목 — 문자 목록에서 **본문 첫 줄 대신** 이게 보인다.
#: 안 주면 `[피트니스스타 화순점]` 이 잘려서 무슨 문자인지 모른다.
_SMS_SUBJECT = "수업 만족도 여쭙습니다"

#: 회원에게 나가는 본문
#:
#: **연장 이야기를 안 꺼낸다.** 7회차에 "연장하실래요" 로 시작하면 영업
#: 문자로 읽힌다 — 설문 안에 그 문항이 있으니 들어가서 답하면 된다.
#:
#: **"트레이너에게 그대로 전해지지 않는다" 를 넣는다.** 솔직하게 쓰게 만드는
#: 문장이라 링크를 누르기 **전에** 읽혀야 한다 (설문 화면에도 같은 말이 있다).
_SMS_TEMPLATE = """[피트니스스타 {branch}]

{member}, 안녕하세요.
{trainer} 트레이너와의 수업이 {session}회차를 지났습니다.

수업이 잘 맞으셨는지, 바라시는 점은 없는지 여쭙고 싶습니다.
남겨 주신 답변은 트레이너에게 그대로 전해지지 않으니 편하게 적어 주세요.

{url}

더 잘 맞는 수업으로 보답하겠습니다."""


def _member_label(name: str | None) -> str:
    """`장예진님` · `정훈` 이 섞여 있다 — 붙은 `님` 을 떼고 하나로 맞춘다.

    안 맞추면 `장예진님 회원님` 처럼 두 번 붙는다.
    """
    clean = (name or "").strip()
    while clean.endswith("님"):
        clean = clean[:-1].rstrip()
    return f"{clean} 회원님" if clean else "회원님"

router = APIRouter(prefix="/session-signs", tags=["session-signs"])


async def _open_pt_survey(
    db: AsyncSession, registration: Registration, sign: SessionSign, trainer_id: str
) -> PtSurvey | None:
    """신규 등록권의 7회차면 **만족도 폼을 하나 연다** (2026-08-20 요청).

    **신규만이다.** 재등록한 사람은 이미 겪어 보고 다시 온 것이라
    7회차에 "연장하실래요" 를 다시 묻는 것이 어색하다.

    **만든 줄을 돌려준다** — 문자는 커밋한 **뒤에** 보낸다 ([_sms_pt_survey]).
    커밋 전에 보내면 싸인이 되돌려졌을 때 없는 설문 주소가 회원에게 가 있다.

    받는 트레이너는 **그날 실제로 수업한 사람**이다. 등록권의 담당으로 하면
    대타로 들어간 날 물어본 것이 엉뚱한 사람에게 붙는다.
    """
    if registration.type != RegistrationType.NEW or sign.session_no != PT_SURVEY_AT:
        return None
    # 되돌렸다 다시 찍는 일이 있어도 두 줄이 안 생긴다 (등록권당 하나다)
    exists = await db.scalar(
        select(PtSurvey.id).where(PtSurvey.registration_id == registration.id)
    )
    if exists is not None:
        return None
    survey = PtSurvey(
        registration_id=registration.id,
        member_id=registration.member_id,
        trainer_id=trainer_id,
        token=public_token(),
        session_no=sign.session_no,
    )
    db.add(survey)
    return survey


async def _sms_pt_survey(db: AsyncSession, survey: PtSurvey) -> None:
    """7회차 설문 주소를 **회원에게** 문자로 보낸다 (2026-09-09 대표 요청).

    예전에는 줄만 만들고 트레이너가 `GET /pt-surveys` 의 주소를 복사해 직접
    보냈다. 발신번호가 지점마다 정해지면서(`branches.sms_sender`) 자동으로
    나갈 수 있게 됐다 — 컴플레인 해결 문자와 **같은 부품**을 쓴다.

    **커밋 뒤에 부른다.** 싸인이 되돌려졌는데 문자가 나가 있으면 회원에게
    없는 설문 주소를 보낸 셈이 된다.

    **발신번호는 그 트레이너의 지점 번호다.** 회원이 되걸면 그 매장에 닿아야
    한다 — 번호가 없으면 **안 보낸다.** 기본 번호로 대신 보내면 화순 회원이
    첨단으로 전화하는 셈이다 (컴플레인 문자와 같은 규칙).

    **실패해도 그냥 넘어간다.** 문자는 곁가지고, 여기서 막으면 솔라피가
    죽었을 때 세션 싸인 자체가 안 된다. 안 나갔으면 `sent_at` 이 비어 있어서
    앱의 `주소 복사` 로 손으로 넘길 수 있다.
    """
    if survey.sent_at:
        return
    member = await db.get(Member, survey.member_id)
    to = (member.phone or "").strip() if member else ""
    if not to:
        return

    trainer = await db.get(Employee, survey.trainer_id)
    branch = await db.get(Branch, trainer.branch_id) if trainer and trainer.branch_id else None
    sender = (branch.sms_sender or "").strip() if branch else ""
    if not sender or not sms.ready(sender):
        logger.info(
            "[pt-survey-sms] 발신번호가 없어 건너뜀 branch=%s", branch.name if branch else "?"
        )
        return

    base = settings.public_base_url.rstrip("/")
    text = _SMS_TEMPLATE.format(
        branch=sms.branch_label(branch.name),
        member=_member_label(member.name),
        trainer=(trainer.name if trainer else "담당"),
        session=survey.session_no,
        url=f"{base}/pt/{survey.token}",
    )
    try:
        await asyncio.to_thread(
            sms.send_sync, to, text,
            sender=sender, subject=_SMS_SUBJECT, tag="pt-survey-sms",
        )
    except Exception:
        logger.warning("[pt-survey-sms] 발송 실패 — 싸인은 그대로 둔다", exc_info=True)
        return
    survey.sent_at = datetime.now(timezone.utc)
    await db.commit()


def _sign_out(
    sign: SessionSign,
    member_name: str | None,
    total_sessions: int | None,
    reg_type,
    skipped_by_name: str | None = None,
) -> SessionSignOut:
    """SessionSignOut + 앱 기록 표시용 조인값(회원명·총 회차·신규/재등록·생략한 사람)."""
    out = SessionSignOut.model_validate(sign)
    out.member_name = member_name
    out.total_sessions = total_sessions
    out.registration_type = reg_type
    # 모델에는 이름이 없다 — id 가 차 있으면 생략이다
    out.signature_skipped = sign.signature_skipped_by_id is not None
    out.signature_skipped_by_name = skipped_by_name
    return out


async def _require_workout(db: AsyncSession, registration: Registration) -> None:
    """이번에 찍을 회차의 **운동일지가 있어야 싸인이다** (2026-08-31 대표 요청).

    일지를 안 써도 싸인이 되면 회차는 줄어드는데 그날 뭘 했는지가 어디에도
    안 남는다. 회원이 공개 주소로 자기 기록을 보는 화면이 생기면서 그 구멍이
    그대로 드러났다 — 찍힌 회차와 일지 수가 안 맞는다.

    **회차를 세는 자리가 둘이라 옮겨 담아야 한다.**

    | | 세는 법 | 재등록하면 |
    |---|---|---|
    | 싸인 | `registration.used_sessions + 1` | **1 로 돌아간다** |
    | 일지 | 회원의 `max(session_no) + 1` | 11·12 로 이어진다 |

    그래서 등록권 하나만 보면 재등록한 회원이 전부 막힌다. 회원의 **모든**
    등록권에서 쓴 회차를 더해 누적 회차로 바꾼 뒤 그 번호의 일지를 찾는다.
    """
    used = await db.scalar(
        select(func.coalesce(func.sum(Registration.used_sessions), 0)).where(
            Registration.member_id == registration.member_id
        )
    )
    session_no = int(used or 0) + 1
    exists = await db.scalar(
        select(WorkoutLog.id).where(
            WorkoutLog.member_id == registration.member_id,
            WorkoutLog.kind == WorkoutKind.PT,
            WorkoutLog.session_no == session_no,
        )
    )
    if exists is None:
        raise HTTPException(
            400,
            detail={
                "code": "NO_WORKOUT_LOG",
                "message": f"{session_no}회차 운동일지를 먼저 써 주세요",
            },
        )


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
    await _require_workout(db, registration)

    # 싸인을 생략하려면 **그렇다고 말해야 한다** (2026-09-05 요청).
    # 그냥 빈 서명을 받아 주면 앱이 이미지를 못 만든 버그와 갈리지 않는다.
    if not payload.skip_signature and not (payload.signature_base64 or "").strip():
        raise HTTPException(
            400, detail={"code": "SIGNATURE_REQUIRED", "message": "싸인을 받아 주세요"}
        )

    performer_id = payload.performed_by_trainer_id or current.id
    performer = current if performer_id == current.id else await db.get(Employee, performer_id)
    if performer is None:
        raise HTTPException(400, detail={"code": "TRAINER_NOT_FOUND", "message": "수행 트레이너가 존재하지 않습니다"})

    # 생략이면 이미지가 아예 없다 — 대신 **누가 올렸는지**를 남긴다.
    # 수행 트레이너가 아니라 버튼을 누른 사람이다 (대타를 지정해도 책임은 누른 쪽이다)
    skipped = payload.skip_signature
    signature_url = None if skipped else save_signature(payload.signature_base64)
    sign = SessionSign(
        registration_id=registration.id,
        member_id=registration.member_id,
        performed_by_trainer_id=performer_id,
        session_no=registration.used_sessions + 1,
        signature_url=signature_url,
        signature_skipped_by_id=current.id if skipped else None,
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
    survey = await _open_pt_survey(db, registration, sign, performer_id)

    await db.commit()
    # **커밋한 뒤에** 보낸다 — 위 트랜잭션이 되돌려지면 없는 설문 주소가 간다
    if survey is not None:
        await _sms_pt_survey(db, survey)
    await db.refresh(sign)
    await db.refresh(registration)
    member = await db.get(Member, registration.member_id)
    return SessionSignResult(
        sign=_sign_out(
            sign,
            member.name if member else None,
            registration.total_sessions,
            registration.type,
            current.name if skipped else None,
        ),
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
    # 싸인을 생략한 사람은 **별칭으로** 붙인다 — 아래 지점 거르기가 수행 트레이너로
    # `Employee` 를 이미 쓰고 있어서, 같은 표를 두 번 쉽게 쓰려면 이름을 나눠야 한다.
    # 생략이 아닌 줄이 훨씬 많으므로 **outer** 조인이다.
    skipper = aliased(Employee)
    stmt = (
        select(
            SessionSign,
            Member.name,
            Registration.total_sessions,
            Registration.type,
            skipper.name,
        )
        .join(Member, Member.id == SessionSign.member_id)
        .join(Registration, Registration.id == SessionSign.registration_id)
        .outerjoin(skipper, skipper.id == SessionSign.signature_skipped_by_id)
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
    return [
        _sign_out(sign, name, total, rtype, skipped_by)
        for sign, name, total, rtype, skipped_by in rows
    ]
