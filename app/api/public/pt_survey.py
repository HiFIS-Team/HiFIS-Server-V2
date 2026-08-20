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
    await db.commit()

    trainer = await db.get(Employee, survey.trainer_id)
    # 접수됐다는 것만 알려준다 — 낸 내용을 돌려주면 링크를 주운 사람도 읽는다
    return {"trainerName": trainer.name if trainer else ""}
