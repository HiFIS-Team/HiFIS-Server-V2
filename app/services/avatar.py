"""아바타 색 팔레트 — 가입/생성 시 순번대로 분산 배정 (CLAUDE.md §2.2).

기존엔 모두 기본값 #6366f1 로 몰렸음 → 직원 수 기준 라운드로빈으로 골고루.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.staff.employee import Employee

# 16색 팔레트(Tailwind 계열, 첫 색 = 기존 기본값). 직원 수 % 16 으로 분산.
AVATAR_PALETTE: list[str] = [
    "#6366f1",  # indigo
    "#f43f5e",  # rose
    "#f59e0b",  # amber
    "#10b981",  # emerald
    "#0ea5e9",  # sky
    "#8b5cf6",  # violet
    "#14b8a6",  # teal
    "#f97316",  # orange
    "#ec4899",  # pink
    "#06b6d4",  # cyan
    "#84cc16",  # lime
    "#d946ef",  # fuchsia
    "#3b82f6",  # blue
    "#ef4444",  # red
    "#22c55e",  # green
    "#a855f7",  # purple
]


def avatar_color_for(index: int) -> str:
    return AVATAR_PALETTE[index % len(AVATAR_PALETTE)]


async def next_avatar_color(db: AsyncSession) -> str:
    """다음 가입자 색 — 현재 직원 수를 인덱스로 라운드로빈(삭제 포함 총계라 재사용 최소)."""
    count = (await db.execute(select(func.count()).select_from(Employee))).scalar() or 0
    return avatar_color_for(count)
