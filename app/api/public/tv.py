"""매장 TV — 해결된 컴플레인을 돌려 보여주는 **로그인 없는** 화면.

지점마다 주소가 하나씩이고(`branches.tv_token`), TV 브라우저를 전체화면으로
띄워 두면 된다. 세로(9:16)로 세운 화면 기준으로 만들었다.

**회원이 보는 자리다.** 그래서 두 가지를 지킨다.

1. **회원 이름·연락처를 가려서 내보낸다** — `김○후` · `···1234`
   (2026-09-08 대표 요청. 그 전에는 아예 안 보냈다).
   추첨 참가자를 거는 것과 **같은 방식**이라 한 화면에서 규칙이 안 갈린다.
   원문 이름·전화번호는 여전히 안 나간다
2. **해결 완료된 것만** 내보낸다. 아직 처리 중인 불만이 벽에 걸리면 안 된다

컴플레인 자체는 `kindness_surveys.improvement` 다 — 설문에서 개선 의견을
적으면 그 줄이 곧 컴플레인 한 건이고, 처리 상태도 같은 줄에 붙어 있다.

**화면은 여기서 안 그린다 (2026-08-20).** `HiFIS-Client-V2` 가 `hifis.app` 에서
그리고, 이 라우터는 값만 준다.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.core.periods import now_kst
from app.enums import ComplaintStatus, ProjectRequestStatus
from app.models.platform.draw import Draw
from app.models.scoring.env import EnvTaskLog
from app.models.scoring.kindness import KindnessSurvey
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.schemas.base import CamelModel
from app.services.draws import draw_period, mask_name, mask_phone

router = APIRouter(tags=["tv"])

#: 이보다 짧은 개선 의견은 화면에 안 올린다.
#:
#: 적을 게 없을 때 `-` · `없음` 처럼 한두 글자를 적고 넘어가는 사람이 있어서
#: 실제로 그런 줄이 쌓여 있다. 그게 TV 에 `없음 → 해결 완료` 로 걸리면 이상하다.
#: **길이만 본다** — 내용을 보고 판단하기 시작하면 진짜 의견까지 걸러진다.
_MIN_TEXT = 4

#: 환경정비에서 TV 로 올라오는 항목 — `kindness.py` 의 같은 이름과 맞춰야 한다
_CLAIM_ITEM = "클레임해결"


class ResolvedOut(CamelModel):
    """해결된 컴플레인 한 건 — **화면에 그릴 것만** 담는다."""

    id: str
    text: str
    resolved_at: str
    #: 의견을 남긴 회원 — **가린 것만** 나간다 (`김○후` · `···1234`).
    #:
    #: 해결 날짜 옆에 세워서 **사람이 한 말**이라는 것이 보이게 한다
    #: (2026-09-08 대표 요청). 가리는 법은 추첨 참가자와 같은 함수다 —
    #: 같은 화면에 둘이 같이 서는데 규칙이 갈리면 안 된다.
    #:
    #: **환경정비에서 온 줄은 빈 값이다** (2026-09-09) — 직원이 손으로 남긴
    #: 것이라 누가 말했는지를 모른다. 화면은 이름이 비면 그 칸을 안 그린다.
    name: str
    phone: str


class TvOut(CamelModel):
    branch_name: str
    resolved: list[ResolvedOut]


class EntryOut(CamelModel):
    """추첨 참가자 한 명 — **가린 이름만** 나간다.

    화면이 칸마다 이름을 적어야 해서 참가자를 다 내보낸다. 그래서 원문 이름과
    전화번호는 절대 실지 않는다 — 벽에 걸린 주소를 아는 사람이 그 달 설문을
    낸 회원 명단을 통째로 보게 된다.

    같은 이름이 둘일 때를 위해 번호 뒤 네 자리를 붙여 준다 (`···1234`).
    """

    name: str
    phone: str


class DrawOut(CamelModel):
    """그 달 추첨 — 매장 TV 가 게임으로 굴린다.

    **당첨자는 이미 정해져 있다** (`winnerIndexes`, 세 명). 화면은 그 셋이
    1·2·3등이 되도록 이름을 붙일 뿐이고, `seed` 는 굴러가는 모양만 정한다.
    그래서 TV 를 껐다 켜도 같은 공이 같은 길로 굴러 같은 사람에게 떨어진다.
    """

    period: str
    game: str
    seed: str
    entries: list[EntryOut]
    #: 참가자가 없으면 빈 배열 — 그 달 설문이 한 건도 없던 지점이다.
    #: 셋보다 적게 냈으면 그만큼만 들어 있다.
    winner_indexes: list[int] = []


async def _branch_of(token: str, db: AsyncSession) -> Branch:
    branch = await db.scalar(select(Branch).where(Branch.tv_token == token))
    if branch is None:
        raise HTTPException(
            404, detail={"code": "TV_NOT_FOUND", "message": "TV 주소가 올바르지 않습니다"}
        )
    return branch


@router.get("/tv/{token}", include_in_schema=False)
async def tv_page(token: str) -> RedirectResponse:
    """옛 주소 — **화면이 있는 곳으로 넘긴다** (2026-08-20).

    TV 브라우저에 옛 주소가 즐겨찾기로 박혀 있을 수 있어서 라우트를 안 지운다.
    몇 달씩 켜 두는 화면이라 어느 날 갑자기 안 뜨면 아무도 원인을 모른다.
    """
    base = settings.public_base_url.rstrip("/")
    return RedirectResponse(f"{base}/tv/{token}", status_code=308)


@router.get("/tv/{token}/draw", response_model=DrawOut)
async def tv_draw(token: str, db: AsyncSession = Depends(get_db)) -> DrawOut:
    """그 달 추첨 결과 — **읽기만 한다. 여기서 뽑지 않는다.**

    뽑는 것은 매월 1일에 도는 잡이다 (`workers/monthly_draw.py`). 화면이 열릴
    때 뽑게 두면 **TV 를 새로고침할 때마다 당첨자가 바뀐다.**

    아직 안 뽑힌 달이면 404 다 — 화면은 그때 게임을 안 틀고 컴플레인만
    보여주면 된다.
    """
    branch = await _branch_of(token, db)
    period = draw_period(now_kst())
    draw = await db.scalar(
        select(Draw).where(Draw.branch_id == branch.id, Draw.period == period)
    )
    if draw is None:
        raise HTTPException(
            404, detail={"code": "DRAW_NOT_FOUND", "message": "이번 달 추첨이 아직 없습니다"}
        )
    return DrawOut(
        period=draw.period,
        game=str(draw.game),
        seed=draw.seed,
        entries=[
            EntryOut(name=mask_name(e.get("name", "")), phone=mask_phone(e.get("phone", "")))
            for e in draw.entries
        ],
        winner_indexes=list(draw.winner_indexes or []),
    )


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

    # 환경정비에서 온 것 — 직원이 칩으로 올리고 **대표가 승인한** 클레임해결
    # (2026-09-09 요청). 회원 설문을 안 거친 컴플레인(말로 들은 것)이 여기 온다.
    #
    # **요약이 있는 것만 건다.** 직원이 적은 원문은 `바벨 중앙 표시목 부착`
    # 처럼 안쪽 말이라 벽에 걸 글이 아니다 — 승인될 때 다듬어 둔 줄을 쓴다.
    env_rows = (
        await db.scalars(
            select(EnvTaskLog)
            .where(
                EnvTaskLog.branch_id == branch.id,
                EnvTaskLog.item_name == _CLAIM_ITEM,
                EnvTaskLog.approval_status == ProjectRequestStatus.APPROVED,
                EnvTaskLog.summary.is_not(None),
                EnvTaskLog.decided_at.is_not(None),
            )
            .order_by(EnvTaskLog.decided_at.desc())
            .limit(30)
        )
    ).all()

    resolved = [
        *(
            ResolvedOut(
                id=r.id,
                # **요약이 있으면 그걸 쓴다** (2026-09-08 대표 요청). 화면이 줄을
                # 두 줄까지만 그려서 길게 적은 의견이 `...` 로 끊겼다. 요약은
                # 해결 완료로 넘어갈 때 한 번 만들어 박아 두므로(`_make_summary`)
                # 여기서 부를 것이 없다 — 화면이 다시 받아도 같은 문장이다.
                #
                # 비어 있으면 원문이다 — 짧아서 안 줄인 것이거나 요약을 못 만든 것.
                text=((r.summary or "").strip() or (r.improvement or "").strip()),
                resolved_at=r.resolved_at.isoformat(),
                name=mask_name(r.member_name or ""),
                phone=mask_phone(r.member_phone or ""),
            )
            for r in rows
            if len((r.improvement or "").strip()) >= _MIN_TEXT
        ),
        *(
            ResolvedOut(
                id=log.id,
                text=(log.summary or "").strip(),
                resolved_at=log.decided_at.isoformat(),
                # **이름·번호를 안 싣는다** — 직원이 손으로 남긴 것이라
                # 누가 말한 컴플레인인지를 모른다. 화면은 빈 값이면 그 칸을
                # 통째로 안 그린다 (`TvBoard.tsx` 의 `{r.name && …}`).
                name="",
                phone="",
            )
            for log in env_rows
        ),
    ]
    # 두 갈래를 **한 줄기로 세운다** — 화면에는 `해결 완료` 한 목록이라
    # 어디서 왔는지가 아니라 언제 끝났는지로 서야 한다
    resolved.sort(key=lambda r: r.resolved_at, reverse=True)
    return TvOut(branch_name=branch.name, resolved=resolved[:30])
