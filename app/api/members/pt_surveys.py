"""PT 만족도 폼 결과 보기 — **직원용** (2026-08-20).

회원이 답하는 길은 `app/api/public/pt_survey.py` 다 (로그인 없음).
여기는 그 결과를 읽는 자리라 로그인이 필요하다.

## 담당 트레이너 본인은 못 본다 (2026-08-20 결정)

**회원에게 "트레이너에게는 전달되지 않아요" 라고 적어 두었다.** 화면에만
적고 서버가 안 막으면 그건 거짓말이다.

| 누가 | 무엇을 |
|---|---|
| MASTER · ADMIN | 전사 |
| MANAGER (점장) | 자기 지점 — **단 본인이 수업한 것은 빠진다** |
| MEMBER (트레이너) | **못 본다** |

점장도 트레이너로 수업한다(backend-gap 24). 그래서 권한이 아니라
**`trainer_id` 로 가른다** — 누구든 자기가 받은 평가는 안 보인다.

회원이 솔직하게 못 적으면 이 폼은 있으나 마나다. 동료 평가를 점장에게
안 여는 것과 같은 이유다 (backend-gap 33).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import branch_filter, require_role
from app.db.session import get_db
from app.models.members.member import Member
from app.models.members.pt_survey import PtSurvey
from app.enums import Role
from app.models.staff.employee import Employee
from app.schemas.members.pt_survey import PtSurveyOut

router = APIRouter(prefix="/pt-surveys", tags=["pt-surveys"])


@router.get("", response_model=list[PtSurveyOut])
async def list_pt_surveys(
    # MANAGER 부터 — 트레이너(MEMBER)는 아예 못 본다
    current: Employee = Depends(require_role(Role.ADMIN, Role.MANAGER)),
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_filter),
    trainer_id: str | None = Query(None, alias="trainerId"),
    #: 안 낸 것만 — 누구에게 다시 물어봐야 하는지 보는 자리
    unanswered: bool = Query(False),
) -> list[PtSurveyOut]:
    """결과 목록 — **본인이 수업한 것은 누구에게도 안 보인다.**"""
    stmt = (
        select(PtSurvey, Member.name, Employee.name)
        .join(Member, Member.id == PtSurvey.member_id)
        .join(Employee, Employee.id == PtSurvey.trainer_id)
        .where(PtSurvey.trainer_id != current.id)  # 자기가 받은 평가는 못 본다
        .order_by(PtSurvey.created_at.desc())
    )
    if trainer_id:
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
