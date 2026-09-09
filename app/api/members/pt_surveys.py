"""PT 만족도 폼 결과 보기 — **직원용** (2026-08-20).

회원이 답하는 길은 `app/api/public/pt_survey.py` 다 (로그인 없음).
여기는 그 결과를 읽는 자리라 로그인이 필요하다.

## 누가 무엇을 보나 (2026-09-09 대표 결정으로 바뀌었다)

| 누가 | 무엇을 |
|---|---|
| MASTER · ADMIN | **전부** |
| MANAGER · MEMBER | **본인이 수업한 것만** |

**예전에는 정반대였다** — 누구든 자기가 받은 평가는 못 봤고 트레이너는
아예 403 이었다. 회원 설문에 "트레이너에게는 전달되지 않아요" 라고 적어
두었기 때문이다.

**그 문구를 걷어내면서 같이 풀었다.** 지금 설문은 "가감 없이 솔직하게 적어
주세요 · 센터 발전을 위해 적극적으로 반영하겠습니다" 라고만 말한다 —
안 보여준다는 약속을 안 하므로 본인에게 보여줘도 어긋나지 않는다.
바뀔 때 **답변이 한 건도 없었다**(운영 12건 전부 미응답), 그래서 옛 약속을
믿고 적은 사람이 없다.

점장도 트레이너로 수업하므로(backend-gap 24) 권한이 아니라
**`trainer_id` 로 가른다** — 점장이라고 남의 것까지 보지는 않는다.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import branch_filter, get_current_user
from app.db.session import get_db
from app.models.members.member import Member
from app.models.members.pt_survey import PtSurvey
from app.enums import Role
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
    """결과 목록 — 대표·관리자는 전부, 나머지는 **본인이 수업한 것만.**"""
    stmt = (
        select(PtSurvey, Member.name, Employee.name)
        .join(Member, Member.id == PtSurvey.member_id)
        .join(Employee, Employee.id == PtSurvey.trainer_id)
        .order_by(PtSurvey.created_at.desc())
    )
    # 점장도 트레이너로 수업한다 — 권한이 아니라 `trainer_id` 로 가른다
    if current.role not in (Role.MASTER, Role.ADMIN):
        stmt = stmt.where(PtSurvey.trainer_id == current.id)
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
