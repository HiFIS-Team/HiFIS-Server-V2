"""지난달 랭킹을 찍어 굳힌다 — 1일 00:00 (2026-09-16 대표 요청)

랭킹은 매번 원본(등록권 결제액·점수 원장)에서 다시 셌다. 그래서 **지난
데이터를 고치면 지난 랭킹이 같이 움직였다** — 9월에 잘못 넣은 등록권을
0원으로 고쳤더니 그 달 매출 순위가 바뀌었다. 전달 통계는 그 달로 끝나야 한다.

**추첨(`monthly_draw`)보다 먼저 돌아야 한다.** 추첨이 랭킹을 보고 뽑는데
그 사이에 원본이 바뀌면 뽑은 사람과 판이 어긋난다.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.periods import KST
from app.db.session import SessionLocal
from app.models.scoring.ranking_freeze import RankingFreeze
from app.models.staff.branch import Branch
from app.services.ranking_board import build_board

logger = logging.getLogger(__name__)


def _previous_period(today) -> str:
    first = today.replace(day=1)
    last_month = first - timedelta(days=1)
    return f"{last_month.year}-{last_month.month:02d}"


async def freeze_previous_month(period: str | None = None) -> int:
    """전달 판을 **지점별로 따로** 찍는다 — 몇 줄을 찍었는지 돌려준다

    지점을 고르면 순위가 그 안에서 다시 매겨져서, 전사 판 하나로는 지점 화면을
    못 만든다. 그래서 `전 지점`(null) + 지점 수만큼 찍는다.

    **이미 찍힌 달은 안 덮는다.** 굳히는 것이 목적이라 다시 돌아도 그대로다.
    """
    async with SessionLocal() as db:
        target = period or _previous_period(
            datetime.now(timezone.utc).astimezone(KST).date()
        )
        # HQ 는 랭킹에 안 선다 (대표·관리자뿐이다 — `build_board` 가 뺀다)
        scopes: list[str | None] = [None]
        scopes += [
            b.id
            for b in (await db.scalars(select(Branch).where(Branch.type != "HQ"))).all()
        ]

        made = 0
        for scope in scopes:
            exists = await db.scalar(
                select(RankingFreeze.id).where(
                    RankingFreeze.period == target,
                    RankingFreeze.branch_id.is_(None)
                    if scope is None
                    else RankingFreeze.branch_id == scope,
                )
            )
            if exists is not None:
                continue
            rows = await build_board(db, period=target, branch_id=scope)
            db.add(
                RankingFreeze(period=target, branch_id=scope, rows=rows)
            )
            made += 1
        await db.commit()
        logger.info("[ranking-freeze] %s — %d개 판을 굳혔다", target, made)
        return made
