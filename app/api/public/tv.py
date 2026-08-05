"""매장 TV — 해결된 컴플레인을 돌려 보여주는 **로그인 없는** 화면.

지점마다 주소가 하나씩이고(`branches.tv_token`), TV 브라우저를 전체화면으로
띄워 두면 된다. 세로(9:16)로 세운 화면 기준으로 만들었다.

**회원이 보는 자리다.** 그래서 두 가지를 지킨다.

1. **회원 이름·연락처를 아예 안 내보낸다.** 컴플레인에 사람 이름이 붙으면
   누가 무슨 불만을 냈는지가 매장에 걸리는 셈이다
2. **해결 완료된 것만** 내보낸다. 아직 처리 중인 불만이 벽에 걸리면 안 된다

컴플레인 자체는 `kindness_surveys.improvement` 다 — 설문에서 개선 의견을
적으면 그 줄이 곧 컴플레인 한 건이고, 처리 상태도 같은 줄에 붙어 있다.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.enums import ComplaintStatus
from app.models.scoring.kindness import KindnessSurvey
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.schemas.base import CamelModel

router = APIRouter(tags=["tv"])

_PAGE = Path(__file__).resolve().parent.parent.parent / "web" / "tv.html"

#: 이보다 짧은 개선 의견은 화면에 안 올린다.
#:
#: 적을 게 없을 때 `-` · `없음` 처럼 한두 글자를 적고 넘어가는 사람이 있어서
#: 실제로 그런 줄이 쌓여 있다. 그게 TV 에 `없음 → 해결 완료` 로 걸리면 이상하다.
#: **길이만 본다** — 내용을 보고 판단하기 시작하면 진짜 의견까지 걸러진다.
_MIN_TEXT = 4


class ResolvedOut(CamelModel):
    """해결된 컴플레인 한 건 — **화면에 그릴 것만** 담는다."""

    id: str
    text: str
    resolved_at: str


class TvOut(CamelModel):
    branch_name: str
    resolved: list[ResolvedOut]


async def _branch_of(token: str, db: AsyncSession) -> Branch:
    branch = await db.scalar(select(Branch).where(Branch.tv_token == token))
    if branch is None:
        raise HTTPException(
            404, detail={"code": "TV_NOT_FOUND", "message": "TV 주소가 올바르지 않습니다"}
        )
    return branch


@router.get("/tv/{token}", response_class=HTMLResponse, include_in_schema=False)
async def tv_page(token: str, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    await _branch_of(token, db)
    return HTMLResponse(_PAGE.read_text(encoding="utf-8"))


@router.get("/tv/{token}/resolved", response_model=TvOut)
async def tv_resolved(token: str, db: AsyncSession = Depends(get_db)) -> TvOut:
    """그 지점에서 **해결 완료된** 컴플레인 — 최근 것부터.

    지점은 **칭찬받은 직원의 소속**으로 가린다. 설문에 지점 컬럼이 따로 없고,
    설문은 그 지점 사람을 칭찬하며 들어온 것이라 그 사람의 지점이 곧 매장이다.
    """
    branch = await _branch_of(token, db)

    rows = (
        await db.scalars(
            select(KindnessSurvey)
            .join(Employee, Employee.id == KindnessSurvey.praised_employee_id)
            .where(
                Employee.branch_id == branch.id,
                KindnessSurvey.improvement_status == ComplaintStatus.DONE,
                KindnessSurvey.resolved_at.is_not(None),
            )
            .order_by(KindnessSurvey.resolved_at.desc())
            .limit(30)
        )
    ).all()

    return TvOut(
        branch_name=branch.name,
        resolved=[
            ResolvedOut(
                id=r.id,
                text=(r.improvement or "").strip(),
                resolved_at=r.resolved_at.isoformat(),
            )
            for r in rows
            if len((r.improvement or "").strip()) >= _MIN_TEXT
        ],
    )
