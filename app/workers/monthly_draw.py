"""달마다 도는 추첨 잡 — 매월 1일, 지점마다 한 명 (2026-09-01 대표 요청).

전달에 친절도 설문을 낸 회원이 대상이다. 뽑은 결과는 `draws` 에 남고
매장 TV 가 그 달 내내 게임으로 굴려 보여준다.

**HQ 는 건너뛴다** — 매장이 아니라 전사라서 TV 도 설문도 없다.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import now_kst
from app.db.session import SessionLocal
from app.models.platform.draw import Draw
from app.models.staff.branch import Branch
from app.services.draws import draw_period, game_of, new_seed, pick, pool

log = logging.getLogger(__name__)


async def draw_for(db: AsyncSession, branch: Branch, period: str) -> Draw | None:
    """그 지점·그 달 추첨 — **이미 뽑았으면 안 뽑는다.**

    잡이 두 번 돌거나 손으로 다시 불러도 결과가 안 바뀐다. 한 번 TV 에 걸린
    당첨자가 조용히 다른 사람으로 바뀌면 안 된다.
    """
    exists = await db.scalar(
        select(Draw).where(Draw.branch_id == branch.id, Draw.period == period)
    )
    if exists is not None:
        return exists

    entries = await pool(db, branch.id, period)
    draw = Draw(
        branch_id=branch.id,
        period=period,
        game=game_of(period),
        seed=new_seed(),
        entries=entries,
        winner_indexes=pick(entries),
    )
    db.add(draw)
    return draw


async def monthly_draw() -> None:
    """매월 1일 — 전 지점 추첨."""
    period = f"{now_kst().year:04d}-{now_kst().month:02d}"
    async with SessionLocal() as db:
        # HQ 는 type 으로 찾는다 — 이름이 바뀌어도 안전하다 (`app/seed.py` 와 같은 규칙)
        branches = (await db.scalars(select(Branch).where(Branch.type != "HQ"))).all()
        for branch in branches:
            draw = await draw_for(db, branch, period)
            if draw is not None:
                log.info(
                    "추첨 %s %s — 참가 %d명, 당첨 %d명 %s",
                    branch.name,
                    period,
                    len(draw.entries),
                    len(draw.winner_indexes or []),
                    draw.winner_indexes,
                )
        await db.commit()


__all__ = ["draw_for", "draw_period", "monthly_draw"]
