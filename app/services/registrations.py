"""등록권을 만들 때의 공통 판단 — **기존 회원**을 뒤늦게 넣는 경우가 여기 있다.

앱을 켜기 한참 전에 등록했거나 이미 세션이 끝난 회원을 나중에 넣을 수 있어야
한다 (2026-08-21 요청). 그런데 그 지난 실적이 **오늘 실적으로 잡히면 안 된다.**

가르는 값은 딱 하나, **결제일(`purchased_at`)** 이다. `기존` 이라는 등록 종류를
따로 만들지 않는다 — 만들면 매출·점수·급여·통계가 전부 그 값을 따로 봐야 하고,
어디 한 곳이라도 빠뜨리면 그 자리만 조용히 틀린다.

| | 어떻게 되나 |
|---|---|
| 매출 랭킹 | `purchased_at` 으로 거른다 → 지난 달 결제는 이번 달에 안 잡힌다 |
| 방문 경로 점수 | 지난 달 결제면 **안 준다** ([counts_now]) |
| 급여 커미션 | **원래 영향이 없다** — 등록이 아니라 수행한 세션 싸인마다 붙는다 |

두 라우트(`POST /members` 의 첫 등록권, `POST /registrations` 의 재등록)가
같이 쓴다. 한쪽만 고치면 같은 값이 경로에 따라 다르게 처리된다.
"""

from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.periods import KST
from app.enums import RegistrationStatus


def counts_now(purchased_at: datetime | None, *, now: datetime | None = None) -> bool:
    """이번 달 실적으로 칠 결제인가.

    **달 단위로 가른다** — 매출 랭킹·점수가 달로 집계되기 때문이다. 같은 달
    안에서 며칠 늦게 입력한 것은 이번 달 실적이 맞으므로 그대로 친다.

    안 주면(`None`) 지금 결제한 것이라 참이다 — 옛 앱이 이 값을 안 보낸다.
    """
    if purchased_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    return purchased_at.astimezone(KST).strftime("%Y-%m") >= now.astimezone(KST).strftime("%Y-%m")


def initial_status(used_sessions: int, total_sessions: int) -> RegistrationStatus:
    """만들 때의 상태 — **이미 다 쓴 등록권은 처음부터 만료다.**

    이력으로만 넣는 기존 회원(세션이 이미 끝난 사람)이 여기 든다. `ACTIVE` 로
    두면 남은 회차가 0인데 유효한 등록권으로 보여서, 세션 싸인 화면에 뜨고
    누르면 그제서야 막힌다.
    """
    if used_sessions >= total_sessions:
        return RegistrationStatus.EXPIRED
    return RegistrationStatus.ACTIVE


def ensure_used_within(used_sessions: int, total_sessions: int) -> None:
    """이미 쓴 회차가 총 회차를 넘으면 막는다.

    넘으면 남은 회차가 음수가 되어 화면이 `-3회 남음` 으로 뜬다.
    """
    if used_sessions > total_sessions:
        raise HTTPException(
            400,
            detail={
                "code": "USED_OVER_TOTAL",
                "message": "이미 받은 회차가 총 회차보다 많습니다",
            },
        )
