"""PT 만족도 폼 — 신규 회원 **7회차**에 문자로 보내는 **로그인 없는** 페이지.

주소가 담는 값은 `pt_surveys.token` 이다 (회원 id 도 등록권 id 도 아니다 —
문자로 나가는 주소라 새면 갈아 끼울 수 있어야 한다).

**로그인이 없다는 게 이 파일의 전부다.** 그래서 셋을 지킨다.

1. 회원 정보는 **이름만** 내준다. 연락처·결제액·남은 회차 금액은 안 나간다
2. 트레이너도 **이름과 아바타 색만** (매장 QR 설문과 같은 기준)
3. **한 번 내면 다시 못 낸다.** 링크가 문자에 남아 있어서, 안 막으면
   같은 사람이 여러 번 눌러 값이 덮인다

줄은 세션 싸인이 만든다 (`app/api/members/session_signs.py`).
여기는 **열고 답하는 길**만 있다.
"""

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import limiter
from app.db.session import get_db
from app.models.members.member import Member
from app.models.members.pt_survey import PtSurvey
from app.models.members.registration import Registration
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.schemas.members.pt_survey import PtSurveyPageOut, PtSurveySubmit
from app.services import notification_texts as ntext
from app.services.notifications import boss_ids, branch_manager_ids, notify

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pt-survey"])

#: 적은 게 없으면 아예 안 남긴다 — `-` · `없음` 같은 한두 글자가 실제로 쌓인다
#: (매장 TV 가 같은 이유로 4자 미만을 안 올린다)
_MIN_TEXT = 4


async def _survey_of(token: str, db: AsyncSession) -> PtSurvey:
    survey = await db.scalar(select(PtSurvey).where(PtSurvey.token == token))
    if survey is None:
        raise HTTPException(
            404, detail={"code": "PT_SURVEY_NOT_FOUND", "message": "설문 주소가 올바르지 않습니다"}
        )
    return survey


@router.get("/pt-survey/{token}", response_model=PtSurveyPageOut)
async def pt_survey_page(token: str, db: AsyncSession = Depends(get_db)) -> PtSurveyPageOut:
    """화면이 뜰 때 한 번 받는 값 — 누구의, 누구에 대한 설문인지."""
    survey = await _survey_of(token, db)
    member = await db.get(Member, survey.member_id)
    trainer = await db.get(Employee, survey.trainer_id)
    registration = await db.get(Registration, survey.registration_id)
    branch = await db.get(Branch, trainer.branch_id) if trainer and trainer.branch_id else None

    return PtSurveyPageOut(
        member_name=member.name if member else "",
        trainer_name=trainer.name if trainer else "",
        trainer_avatar_color=trainer.avatar_color if trainer else "#2F54EB",
        branch_name=branch.name if branch else "",
        session_no=survey.session_no,
        total_sessions=registration.total_sessions if registration else 0,
        answered=survey.answered_at is not None,
    )


@router.post("/pt-survey/{token}", status_code=201)
@limiter.limit("30/minute")  # IP당 분 30회 — 매장 QR 설문과 같은 기준
async def submit_pt_survey(
    request: Request,
    token: str,
    payload: PtSurveySubmit,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    survey = await _survey_of(token, db)
    if survey.answered_at is not None:
        raise HTTPException(
            400, detail={"code": "ALREADY_ANSWERED", "message": "이미 보내주셨어요"}
        )

    text = (payload.request or "").strip()
    survey.satisfaction = payload.satisfaction
    survey.request = text if len(text) >= _MIN_TEXT else None
    survey.renew = payload.renew
    survey.answered_at = datetime.now(timezone.utc)

    trainer = await db.get(Employee, survey.trainer_id)
    member = await db.get(Member, survey.member_id)

    # **회원의 답을 먼저 못 박는다.** 알림을 같은 커밋에 묶으면 푸시 쪽이 한 번
    # 흔들릴 때 회원이 적어 낸 것까지 같이 되돌아간다 — 여기는 로그인도 없는
    # 자리라 다시 써 달라고 할 방법이 없다.
    await db.commit()

    # 알림은 **덤이다** — 못 보내도 접수는 끝난 것이라 회원에게 오류를 주지 않는다
    try:
        await _notify_answered(db, survey, trainer, member)
        await db.commit()
    except Exception:  # noqa: BLE001 — 알림 실패가 접수를 무르면 안 된다
        logger.exception("PT 만족도 폼 알림 실패 (survey=%s)", survey.id)
        await db.rollback()

    # 접수됐다는 것만 알려준다 — 낸 내용을 돌려주면 링크를 주운 사람도 읽는다
    return {"trainerName": trainer.name if trainer else ""}


async def _notify_answered(
    db: AsyncSession, survey: PtSurvey, trainer: Employee | None, member: Member | None
) -> None:
    """설문이 들어왔다고 알린다 (2026-09-05) — **결과를 볼 수 있는 사람에게만.**

    담당 트레이너 본인은 못 보는 자리라(`app/api/members/pt_surveys.py`) 알림도
    안 보낸다 — 받는 사람은 MASTER·ADMIN(전사)과 그 지점 MANAGER(자기 지점)이고,
    **양쪽 다 그날 수업한 트레이너는 뺀다.** 결과 조회 권한과 똑같이 맞춘 것이다.
    """
    text = ntext.pt_survey_submitted(member.name if member else "", survey.session_no)
    branch_id = trainer.branch_id if trainer else None
    trainer_id = trainer.id if trainer else None
    for eid in await boss_ids(db, exclude=trainer_id):
        await notify(db, employee_id=eid, **text)
    for eid in await branch_manager_ids(db, branch_id, exclude=trainer_id):
        await notify(db, employee_id=eid, **text)
