"""PT 만족도 폼 결과 보기 — **직원용** (2026-08-20).

회원이 답하는 길은 `app/api/public/pt_survey.py` 다 (로그인 없음).
여기는 그 결과를 읽는 자리라 로그인이 필요하다.

**아직 문자를 못 보내는 동안 `url` 이 유일한 출구다** — 발신번호가 정해지기
전까지는 트레이너가 이 주소를 복사해 직접 보낸다.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import branch_filter, get_current_user
from app.db.session import get_db
from app.enums import Role
from app.models.members.member import Member
from app.models.members.pt_survey import PtSurvey
from app.models.staff.employee import Employee
from app.schemas.members.pt_survey import PtSurveyOut

router = APIRouter(prefix="/pt-surveys", tags=["pt-surveys"])


@router.get("", response_model=list[PtSurveyOut])
async def list_pt_surveys(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_filter),
    trainer_id: str | None = Query(None, alias="trainerId"),
    #: 안 낸 것만 — 누구에게 다시 물어봐야 하는지 보는 자리
    unanswered: bool = Query(False),
) -> list[PtSurveyOut]:
    """내 것부터 — **MEMBER 는 자기가 수업한 것만** 본다.

    남의 회원이 트레이너에게 뭘 바라는지는 그 트레이너와 관리자가 볼 일이다
    (동료 평가·근태와 같은 기준 — backend-gap 33·60).
    """
    stmt = (
        select(PtSurvey, Member.name, Employee.name)
        .join(Member, Member.id == PtSurvey.member_id)
        .join(Employee, Employee.id == PtSurvey.trainer_id)
        .order_by(PtSurvey.created_at.desc())
    )
    if current.role == Role.MEMBER:
        stmt = stmt.where(PtSurvey.trainer_id == current.id)
    elif trainer_id:
        stmt = stmt.where(PtSurvey.trainer_id == trainer_id)
    if scope:
        stmt = stmt.where(Employee.branch_id == scope)
    if unanswered:
        stmt = stmt.where(PtSurvey.answered_at.is_(None))

    base = settings.public_base_url.rstrip("/")
    rows = (await db.execute(stmt)).all()
    out = []
    for survey, member_name, trainer_name in rows:
        item = PtSurveyOut.model_validate(survey)
        item.member_name = member_name
        item.trainer_name = trainer_name
        item.url = f"{base}/pt/{survey.token}"
        out.append(item)
    return out
