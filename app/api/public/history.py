"""출석 이력 — 브로제이 출입 기록을 달 단위로 세워 보는 **로그인 없는** 화면.

지점마다 주소가 하나씩이고(`branches.history_token`), 그 주소를 아는 사람만 연다.
설문·TV 와 같은 방식인데 **보는 사람이 다르다** — 이건 매장에 거는 것이 아니라
**직원이 보는 자리다.**

## 두 가지를 지킨다

1. **전화번호는 뒤 네 자리만** 내보낸다. 사람을 가리는 데는 그걸로 충분하고,
   주소가 새더라도 그대로 걸 수 있는 번호는 안 나간다
2. **집 주소는 아예 안 내보낸다.** 브로제이 응답에 `simple_address` 로 들어 있는데
   (`화순군 화순읍 …아파트 101-705`) 출석 순위를 보는 데 쓸 일이 없다

## 지점마다 보는 곳이 다르다

    화순      브로제이(BroJ)   — REST, 그룹이 하나라 키가 설정에 있다
    첨단      다짐(Dagym)      — GraphQL, `branches.dajim_gym_id`
    동광주    다짐(Dagym)

**어느 쪽을 볼지는 지점 행이 정한다.** `dajim_gym_id` 가 채워져 있으면 다짐,
아니면 브로제이 쪽을 본다. 둘 다 아니면 그 지점은 아직 연동이 없다.

다짐은 **회원 상태 칸이 없어서** '적게 나온' 목록의 상태가 `-` 로 나온다
(브로제이는 이용중·만료임박·만료가 뜬다).

## 두 목록을 같이 준다

- **많이 나온 사람** (기본 20일 이상) — 잘 오는 회원
- **적게 나온 사람** (기본 7일 이하) — 연락해서 끌어야 할 회원

연속 출석은 안 쓴다 (2026-08-26 결정). 상품 지급 기준으로 쓰던 것인데
지금 필요한 건 그달 몇 번 왔나다.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.periods import KST
from app.db.session import get_db
from app.models.staff.branch import Branch
from app.schemas.base import CamelModel
from app.services import broj, dajim, gym_history

router = APIRouter(tags=["history"])

#: 회원 상태 → 사람이 읽는 말 (브로제이 `customer_status`)
STATUS_KR = {
    "ACTIVE": "이용중",
    "SOON_INACTIVE": "만료임박",
    "INACTIVE": "만료",
    "UNREGISTERED": "미등록",
}


class MemberOut(CamelModel):
    """한 줄 — **화면에 그릴 것만** 담는다 (집 주소·원본 전화번호는 뺀다)."""

    rank: int
    name: str
    phone: str  # 010-****-1234
    days: int
    last_visit: str  # YYYY-MM-DD
    status: str  # 이용중 · 만료임박 · …


class HistoryOut(CamelModel):
    branch_name: str
    #: 어느 달의 값인가 — 요청에서 달을 안 주면 서버가 이번 달로 정하므로,
    #: 이 값이 없으면 받은 쪽이 무슨 달인지 알 수 없다
    month: str  # YYYY-MM
    high_threshold: int
    low_threshold: int
    high: list[MemberOut]
    low: list[MemberOut]


async def _branch_of(token: str, db: AsyncSession) -> Branch:
    branch = await db.scalar(select(Branch).where(Branch.history_token == token))
    if branch is None:
        raise HTTPException(
            404,
            detail={"code": "HISTORY_NOT_FOUND", "message": "출석 이력 주소가 올바르지 않습니다"},
        )
    return branch


async def _summarize(branch: Branch, start: dt.date, end: dt.date) -> dict:
    """그 지점이 쓰는 곳에서 회원별 출석일을 받아 온다.

    **지점 행이 어느 쪽인지 정한다.** 코드에 지점 이름을 박아 두면 지점을
    하나 더 열 때마다 배포를 해야 한다.
    """
    if branch.dajim_gym_id:
        if not dajim.configured():
            raise HTTPException(
                503,
                detail={
                    "code": "DAJIM_NOT_CONFIGURED",
                    "message": "다짐 설정이 없습니다 (서버 .env 의 DAJIM_* 확인)",
                },
            )
        return await gym_history.cached(
            f"dajim:{branch.dajim_gym_id}:{start}~{end}",
            lambda: dajim.summarize(branch.dajim_gym_id, start, end),
        )

    if branch.name == settings.broj_branch_name:
        if not broj.configured():
            raise HTTPException(
                503,
                detail={
                    "code": "BROJ_NOT_CONFIGURED",
                    "message": "브로제이 설정이 없습니다 (서버 .env 의 BROJ_* 확인)",
                },
            )
        return await broj.summarize(start, end)

    raise HTTPException(
        400,
        detail={
            "code": "HISTORY_NOT_LINKED",
            # 이름 뒤에 '점' 을 붙이지 않는다 — `전 지점` 이 `전 지점점` 이 된다
            "message": f"{branch.name}: 출석 연동이 아직 없습니다",
        },
    )


def _pack(rows: list[tuple], reverse: bool) -> list[MemberOut]:
    """(출석일수, 이름, 전화, 최근방문, 상태) 묶음을 줄 세운다.

    같은 일수면 이름순이라 **새로고침할 때마다 순서가 흔들리지 않는다.**
    """
    ordered = sorted(rows, key=lambda t: (-t[0] if reverse else t[0], t[1]))
    return [
        MemberOut(
            rank=i,
            name=name,
            phone=gym_history.mask_phone(phone),
            days=days,
            last_visit=last.isoformat(),
            status=STATUS_KR.get(status, status or "-"),
        )
        for i, (days, name, phone, last, status) in enumerate(ordered, 1)
    ]


@router.get("/history/{token}", response_model=HistoryOut)
async def history(
    token: str,
    month: str | None = Query(None, description="YYYY-MM (기본: 이번 달)"),
    high: int = Query(20, ge=1, le=31, description="많이 나온 기준 (이상)"),
    low: int = Query(7, ge=1, le=31, description="적게 나온 기준 (이하)"),
    db: AsyncSession = Depends(get_db),
) -> HistoryOut:
    branch = await _branch_of(token, db)
    today = dt.datetime.now(KST).date()
    if month:
        try:
            year, mon = (int(x) for x in month.split("-")[:2])
            start, end = gym_history.month_range(year, mon)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                400, detail={"code": "BAD_MONTH", "message": "달 형식이 올바르지 않습니다"}
            ) from exc
    else:
        start, end = gym_history.month_range(today.year, today.month)

    try:
        by_member = await _summarize(branch, start, end)
    except gym_history.HistoryError as exc:
        # 자격증명 만료가 제일 흔하다 — 화면이 이 문장을 그대로 보여준다
        raise HTTPException(
            502, detail={"code": "HISTORY_FAILED", "message": str(exc)}
        ) from exc
    packed = [
        (len(m["days"]), m["name"], m["phone"], m["last"], m["status"])
        for m in by_member.values()
    ]

    return HistoryOut(
        branch_name=branch.name,
        month=f"{start.year}-{start.month:02d}",
        high_threshold=high,
        low_threshold=low,
        high=_pack([r for r in packed if r[0] >= high], reverse=True),
        low=_pack([r for r in packed if r[0] <= low], reverse=False),
    )
