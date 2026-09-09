"""이모지 반응 서비스 — 토글 + 집계 (CLAUDE.md §6.12).

- toggle_reaction: 같은 (대상·이모지·사람) 있으면 제거, 없으면 추가.
  **사내톡 메시지는 한 사람당 하나뿐이다** — 아래 [ONE_PER_PERSON] 참고.
- aggregate_for: 대상 여러 건의 반응을 { targetId: [{emoji, employeeIds}] } 로 집계.
  공지/회의록 목록 응답에 N+1 없이 한 번에 붙이기 위함.

commit 은 호출자가 담당 (라우터 트랜잭션 경계 유지).
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ReactionTargetType
from app.models.board.reaction import Reaction
from app.schemas.board.reaction import ReactionAgg


#: 한 사람이 **하나만** 달 수 있는 대상 (2026-09-07 요청)
#:
#: 사내톡은 말풍선 하나에 이모지가 계속 쌓였다 — 더블탭으로 ❤️ 를 달아 두고
#: 길게 눌러 😂 를 고르면 둘 다 남아서, 한 사람이 여섯 종을 다 붙일 수 있었다.
#: 알약 줄이 그만큼 길어지고, "이 사람이 이 메시지를 어떻게 봤나"도 흐려진다.
#: 이제 다른 이모지를 고르면 **갈아탄다** (같은 것을 또 누르면 떼는 건 그대로).
#:
#: 공지·회의록·프로젝트는 그대로 여러 개를 받는다 — 거기는 글 하나를 여러
#: 사람이 오래 두고 보는 자리라 ❤️ 와 👍 가 같이 서는 것이 뜻이 있다.
ONE_PER_PERSON = (ReactionTargetType.MESSAGE,)


async def toggle_reaction(
    db: AsyncSession,
    *,
    target_type: ReactionTargetType,
    target_id: str,
    emoji: str,
    employee_id: str,
) -> bool:
    """추가되면 True, 제거되면 False. commit 은 호출자."""
    existing = await db.scalar(
        select(Reaction).where(
            Reaction.target_type == target_type,
            Reaction.target_id == target_id,
            Reaction.emoji == emoji,
            Reaction.employee_id == employee_id,
        )
    )
    if existing is not None:
        await db.delete(existing)
        return False

    # 하나만 받는 대상이면 그 사람이 먼저 달아 둔 것을 뗀다 (갈아타기)
    if target_type in ONE_PER_PERSON:
        others = await db.scalars(
            select(Reaction).where(
                Reaction.target_type == target_type,
                Reaction.target_id == target_id,
                Reaction.employee_id == employee_id,
            )
        )
        for other in others:
            await db.delete(other)

    db.add(
        Reaction(
            target_type=target_type,
            target_id=target_id,
            emoji=emoji,
            employee_id=employee_id,
        )
    )
    return True


def _group(rows: list[Reaction]) -> list[ReactionAgg]:
    by_emoji: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by_emoji[r.emoji].append(r.employee_id)
    return [ReactionAgg(emoji=e, employee_ids=ids) for e, ids in by_emoji.items()]


async def aggregate_for(
    db: AsyncSession, target_type: ReactionTargetType, target_ids: list[str]
) -> dict[str, list[ReactionAgg]]:
    """대상 id 목록 → { targetId: [ReactionAgg] }. 없는 대상은 빈 리스트."""
    result: dict[str, list[ReactionAgg]] = {tid: [] for tid in target_ids}
    if not target_ids:
        return result
    rows = await db.scalars(
        select(Reaction).where(
            Reaction.target_type == target_type,
            Reaction.target_id.in_(target_ids),
        )
    )
    grouped: dict[str, list[Reaction]] = defaultdict(list)
    for r in rows:
        grouped[r.target_id].append(r)
    for tid, rs in grouped.items():
        result[tid] = _group(rs)
    return result


async def aggregate_one(
    db: AsyncSession, target_type: ReactionTargetType, target_id: str
) -> list[ReactionAgg]:
    return (await aggregate_for(db, target_type, [target_id]))[target_id]
