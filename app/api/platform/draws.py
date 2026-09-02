"""달마다 도는 추첨 — **직원이 보는 자리** (2026-09-01).

매장 TV(`api/public/tv.py`)는 로그인 없이 토큰으로 보는 화면이고, 여기는
앱에서 로그인한 직원이 본다. 주는 것이 하나 더 있다 — **찍어 둔 게임 영상**.

## 권한을 안 가린다 (2026-09-01 대표 결정)

직원이 각자 자기 인스타에 올리는 것까지가 목적이라 MASTER 만 여는 자리가
아니다. 대신 **지점은 가린다** — `branch_filter` 라 직원·점장은 자기 지점
것만 보고, MASTER·ADMIN 만 지점을 고르거나 전 지점을 본다.

## 전화번호를 안 준다

TV 는 `···1234` 까지 주는데 여기는 **이름만** 준다. 이 화면에서 하는 일이
'영상을 인스타에 올리는 것'이라 전화번호를 쓸 자리가 없고, 릴스 화면에서도
뺐다 (`HiFIS-Client-V2` 의 `/tv/{token}/reels`).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_filter, get_current_user
from app.db.session import get_db
from app.models.platform.draw import Draw
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.schemas.base import CamelModel, SignedUrlOptional
from app.services.draws import mask_name

router = APIRouter(prefix="/draws", tags=["draws"])

#: 한 번에 돌려주는 달 수 — 지점 셋이면 최대 서른여섯 줄이다
MAX_MONTHS = 12


class DrawWinnerOut(CamelModel):
    """당첨자 한 명 — 이름은 가려서 준다 (`김○후`)."""

    rank: int
    name: str


class MonthDrawOut(CamelModel):
    """그달·그 지점 추첨 한 건.

    **매장 TV 의 `DrawOut` 과 다른 스키마다** (`api/public/tv.py`). 저쪽은
    게임을 굴리는 데 필요한 것(시드·참가자 전원)을 주고, 여기는 **결과와
    영상**만 준다. 이름을 갈라 두지 않으면 OpenAPI 가 둘을
    `app__api__public__tv__DrawOut` 처럼 길게 바꿔 버려서, 앱 계약 테스트가
    이름으로 짝을 못 찾는다 (실제로 걸렸다).
    """

    period: str
    game: str
    branch_id: str
    branch_name: str
    #: 앞에서부터 1·2·3등. 참가자가 셋보다 적으면 그만큼만
    winners: list[DrawWinnerOut]
    #: 그달 참가자 수 — '몇 명 중에서 뽑혔나' 를 보여주는 값
    entry_count: int
    #: 찍어 둔 게임 영상 — **아직 안 구웠으면 null**
    #:
    #: 매월 1일 아침(09:20 KST)에 잡이 굽는다 (`workers/draw_videos.py`). 그 사이거나
    #: 굽다 실패했으면 비어 있다 — 앱은 그때 '준비 중' 으로 그린다.
    video_url: SignedUrlOptional = None
    video_at: datetime | None = None

    #: 영상 **마지막 프레임** — 앱 화면 히어로에 쓴다 (영상과 같이 구워진다)
    poster_url: SignedUrlOptional = None


@router.get("", response_model=list[MonthDrawOut])
async def list_draws(
    branch_id: str | None = Depends(branch_filter),
    period: str | None = Query(None, description="`YYYY-MM` — 안 주면 최근 달부터"),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MonthDrawOut]:
    """볼 수 있는 추첨 — **최근 달부터.**

    직원·점장은 자기 지점 한 줄씩, MASTER·ADMIN 은 지점을 안 고르면 전 지점이
    같이 온다 (그 달 지점 수만큼). 앱 업무 화면의 지점 고르개가 그대로 걸린다.
    """
    q = (
        select(Draw, Branch)
        .join(Branch, Branch.id == Draw.branch_id)
        .order_by(Draw.period.desc(), Branch.name)
    )
    if branch_id:
        q = q.where(Draw.branch_id == branch_id)
    if period:
        q = q.where(Draw.period == period)

    rows = (await db.execute(q.limit(MAX_MONTHS * 8))).all()
    out: list[MonthDrawOut] = []
    seen: set[str] = set()
    for draw, branch in rows:
        seen.add(draw.period)
        if len(seen) > MAX_MONTHS:
            break
        entries = draw.entries or []
        out.append(
            MonthDrawOut(
                period=draw.period,
                game=str(draw.game),
                branch_id=draw.branch_id,
                branch_name=branch.name,
                winners=[
                    DrawWinnerOut(
                        rank=i + 1,
                        name=mask_name((entries[j] or {}).get("name", "")),
                    )
                    for i, j in enumerate(draw.winner_indexes or [])
                    if 0 <= j < len(entries)
                ],
                entry_count=len(entries),
                video_url=draw.video_path,
                video_at=draw.video_at,
                poster_url=draw.poster_path,
            )
        )
    return out


__all__ = ["router"]
