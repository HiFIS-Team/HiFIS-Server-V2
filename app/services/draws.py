"""달마다 도는 추첨 — 대상 명단 · 당첨자 · 이름 가리기 (2026-09-01 대표 결정).

| | |
|---|---|
| 대상 | **전달**에 친절도 설문을 낸 회원 (8월 설문 → 9월 추첨) |
| 지점 | 칭찬받은 직원의 소속으로 가른다 (`api/public/tv.py` 와 같은 규칙) |
| 뽑는 날 | 매월 [DRAW_DAY] 일 (KST) — 잡이 자동으로 돈다 |
| 게임 | 달마다 하나씩 (`DrawGame`) |
"""

import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import period_range
from app.enums import DrawGame
from app.models.scoring.kindness import KindnessSurvey
from app.models.staff.employee import Employee

#: 매월 이 날 뽑는다 (KST). **한 줄만 고치면 날이 바뀐다.**
#:
#: 1일로 둔 이유 — 그 달 내내 TV 에 결과가 걸려 있게 된다. 말일에 뽑으면
#: 하루만 걸리고 다음 달 이벤트가 곧바로 시작된다.
DRAW_DAY = 1

#: 첫 이벤트가 열린 달 — [GAME_ROTATION] 을 여기서부터 센다
FIRST_PERIOD = "2026-09"

#: 그 달에 트는 게임 — **달마다 돌아가며 바뀐다** (2026-09-01 대표 요청).
#:
#: **화면이 있는 것만 넣는다.** 여기 값이 곧 클라이언트가 고르는 장면이라,
#: 안 만든 게임을 넣어 두면 그 달에 TV 가 빈 화면이 된다.
#: `DrawGame.LADDER`·`ROULETTE` 는 화면이 없어서, `PINBALL` 은 **화면은 있는데
#: 재미가 없어서** 빠져 있다 — 공이 하나뿐이라 참가자끼리 겨루는 것이 없고
#: 1등이 한 번도 안 바뀐다 (나머지는 네다섯 번 바뀐다).
#:
#: **차례를 바꾸면 이미 뽑은 달의 게임도 바뀐다.** 뒤에 붙이는 것은 안전하고,
#: 가운데에 끼우면 그달 TV 에 다른 게임이 뜬다 (당첨자는 안 바뀐다 — 시드와
#: 명단이 `draws` 행에 그대로 있어서 어느 게임으로 굴려도 1등이 당첨자다).
GAME_ROTATION = (
    DrawGame.RACE,     # 2026-09
    DrawGame.HOOPS,    # 2026-10
    DrawGame.SOCCER,   # 2026-11
    DrawGame.CURLING,  # 2026-12
    DrawGame.CLAW,     # 2027-01
    DrawGame.SUMO,     # 2027-02
)


def game_of(period: str) -> DrawGame:
    """그 달에 트는 게임 — [FIRST_PERIOD] 부터 한 달에 한 칸씩 돈다.

    **기준 달을 두는 이유** — `연*12+월` 을 그냥 나누면 첫 달에 뭐가 걸릴지를
    사람이 계산해 봐야 안다. 여기서부터 세면 `GAME_ROTATION` 의 차례가 곧
    9월·10월·11월 순서다.
    """
    y0, m0 = int(FIRST_PERIOD[:4]), int(FIRST_PERIOD[5:7])
    year, month = int(period[:4]), int(period[5:7])
    gap = (year - y0) * 12 + (month - m0)
    return GAME_ROTATION[gap % len(GAME_ROTATION)]


def source_period(period: str) -> str:
    """추첨 달 → **설문을 센 달** (2026-09 → 2026-08).

    "8월에 설문 낸 사람이 9월 이벤트 참여" 라는 규칙이 여기 한 줄이다.
    """
    year, month = int(period[:4]), int(period[5:7])
    return f"{year - 1:04d}-12" if month == 1 else f"{year:04d}-{month - 1:02d}"


def mask_name(name: str) -> str:
    """TV 에 띄울 이름 — **가운데를 가린다** (`김은후` → `김○후`).

    회원들이 보는 화면이라 이름을 그대로 걸지 않는다 (2026-09-01 대표 결정).
    당첨자에게는 매장이 따로 연락하므로 화면에는 알아볼 만큼만 있으면 된다.

    두 글자는 뒤를 가리고(`김민` → `김○`), 네 글자 이상은 **가운데를 전부**
    가린다(`남궁민수` → `남○○수`). 한 글자면 가릴 데가 없어 그대로 둔다.
    """
    clean = name.strip()
    if len(clean) <= 1:
        return clean
    if len(clean) == 2:
        return f"{clean[0]}○"
    return f"{clean[0]}{'○' * (len(clean) - 2)}{clean[-1]}"


def mask_phone(phone: str) -> str:
    """뒤 네 자리만 남긴다 — 같은 이름이 둘일 때 가르는 값이다."""
    digits = "".join(c for c in phone if c.isdigit())
    return f"···{digits[-4:]}" if len(digits) >= 4 else "···"


async def pool(db: AsyncSession, branch_id: str, period: str) -> list[dict]:
    """그 지점의 추첨 대상 — **전달 설문을 낸 사람들**.

    **같은 사람이 여러 번 냈어도 한 줄이다** (이름·전화로 묶는다). 안 묶으면
    많이 낸 사람이 그만큼 유리해져서 추첨이 아니라 응모 횟수 경쟁이 된다.

    차례는 **처음 낸 순서**다 — 뽑을 때마다 명단이 흔들리면 지난 추첨을 다시
    틀었을 때 칸이 뒤바뀐다.
    """
    start, end = period_range(source_period(period))
    rows = (
        await db.execute(
            select(KindnessSurvey)
            .join(Employee, Employee.id == KindnessSurvey.praised_employee_id)
            .where(
                Employee.branch_id == branch_id,
                KindnessSurvey.submitted_at >= start,
                KindnessSurvey.submitted_at < end,
                KindnessSurvey.consent.is_(True),
            )
            .order_by(KindnessSurvey.submitted_at)
        )
    ).scalars().all()

    seen: set[tuple[str, str]] = set()
    entries: list[dict] = []
    for row in rows:
        name = (row.member_name or "").strip()
        phone = (row.member_phone or "").strip()
        if not name:
            continue
        key = (name, "".join(c for c in phone if c.isdigit()))
        if key in seen:
            continue
        seen.add(key)
        entries.append({"id": row.id, "name": name, "phone": phone})
    return entries


#: 한 달에 몇 명을 뽑나 (2026-09-01 대표 결정)
WINNERS = 3


def pick(entries: list[dict], count: int = WINNERS) -> list[int]:
    """당첨자를 고른다 — **`secrets` 로 [WINNERS] 명을 겹치지 않게.**

    시드로 뽑지 않는다. 시드는 화면이 굴러가는 모양만 정하고, 당첨은 여기서
    안전하게 정해 행에 박는다. 둘을 섞으면 "화면을 다시 틀면 다른 사람이
    당첨" 이 되거나 "시드를 아는 사람이 결과를 미리 안다" 가 된다.

    **참가자가 모자라면 있는 만큼만** 뽑는다 — 두 명이 냈으면 두 명이다.
    """
    left = list(range(len(entries)))
    out: list[int] = []
    for _ in range(min(count, len(left))):
        out.append(left.pop(secrets.randbelow(len(left))))
    return out


def new_seed() -> str:
    return secrets.token_hex(8)


def draw_period(now_kst: datetime) -> str:
    """오늘이 속한 추첨 달 — [DRAW_DAY] 전이면 아직 지난달 것이 걸려 있다."""
    year, month = now_kst.year, now_kst.month
    if now_kst.day < DRAW_DAY:
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return f"{year:04d}-{month:02d}"
