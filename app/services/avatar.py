"""아바타 색 팔레트 — 가입/생성 시 순번대로 분산 배정 (CLAUDE.md §2.2).

⚠️ 이 18색은 **앱 프로필 고르개(HiFIS-App-V2 profile_screen.dart _avatarColors)와 반드시 동일**해야 한다.
값이 어긋나면 프로필을 열어도 어느 스와치에도 체크가 안 뜬다(앱은 ARGB 정수 비교로 매칭).
저장 포맷도 앱이 쓰는 것과 같은 `#RRGGBB` 대문자. 직원 수 % 18 로 분산.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.staff.employee import Employee

# 앱 디자인 시스템 톤(무채색 베이스)에 맞춘 18색 — 앱 _avatarColors 와 1:1 동일 순서.
AVATAR_PALETTE: list[str] = [
    "#2F54EB", "#2B6BF3", "#5A6ACF", "#3FA7E8", "#3E8FA8", "#3EBFA5",
    "#3FA85C", "#7CA83E", "#C7952F", "#D07E2C", "#E0662B", "#CC3B33",
    "#D03A78", "#BE3ACD", "#8E3AD0", "#6B3AD0", "#3E4A5C", "#64748B",
]


def avatar_color_for(index: int) -> str:
    return AVATAR_PALETTE[index % len(AVATAR_PALETTE)]


async def next_avatar_color(db: AsyncSession) -> str:
    """다음 가입자 색 — 현재 직원 수를 인덱스로 라운드로빈(삭제 포함 총계라 재사용 최소)."""
    count = (await db.execute(select(func.count()).select_from(Employee))).scalar() or 0
    return avatar_color_for(count)
