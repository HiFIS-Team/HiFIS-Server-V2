"""출석 이력 공통 — 브로제이·다짐이 같이 쓴다.

두 서비스는 붙는 방식이 완전히 다르다 (REST vs GraphQL). 그런데 **받아 온
뒤로는 똑같다** — 회원별로 출석한 날을 모아 세고 줄 세우는 일이다.
그래서 각 클라이언트는 아래 모양으로만 맞춰 주면 된다.

    {회원키: {"name": str, "phone": str, "days": set[date],
              "status": str, "last": date}}

`broj_test/report.py` 가 하던 일을 서버 규약에 맞춰 옮겼다.
"""

import asyncio
import datetime as dt
import time
from typing import Any, Awaitable, Callable

from app.core.periods import KST

#: 받아 둔 결과를 들고 있는 시간(초).
#:
#: 출석은 사람이 문을 지날 때 한 건씩 는다. 5분 지난 값을 보는 편이,
#: 페이지를 열 때마다 수십 페이지를 다시 받는 것보다 낫다.
#: 동광주는 한 달이 2만 9천 건(30페이지)이라 특히 그렇다.
CACHE_TTL = 300

_cache: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}


class HistoryError(RuntimeError):
    """바깥 서비스가 못 준다 — 자격증명 만료·장애 등. 화면이 이걸 잡아 안내한다."""


async def cached(key: str, fetch: Callable[[], Awaitable[Any]]) -> Any:
    """[CACHE_TTL] 초 동안 들고 있는다.

    **키마다 락을 따로 둔다.** 하나로 묶으면 화순을 받는 동안 첨단 요청이
    같이 멈춘다. 락을 아예 안 걸면 여러 명이 동시에 열었을 때 각자 수십
    페이지씩 받아서 바깥 서비스를 그만큼 두들긴다.
    """
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]

    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)  # 기다리는 사이 다른 요청이 채웠을 수 있다
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return hit[1]
        value = await fetch()
        _cache[key] = (time.monotonic(), value)
    return value


def to_date(v: Any) -> dt.date | None:
    """무슨 모양으로 오든 날짜로 — ms 타임스탬프 · ISO(`...Z`) · `YYYYMMDD`.

    **전부 KST 로 맞춘다.** UTC 로 두면 오전 9시 이전 출석이 전날로 밀려서,
    일찍 오는 회원의 출석일이 하루씩 어긋난다. 다짐은 `...Z`(UTC) 로 주고
    브로제이는 밀리초로 주는데 둘 다 여기서 같은 기준이 된다.
    """
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit() and len(v) >= 10):
        n = int(v)
        if n > 10_000_000_000:  # 밀리초
            n //= 1000
        return dt.datetime.fromtimestamp(n, KST).date()

    s = str(v).strip()
    if len(s) == 8 and s.isdigit():
        return dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))
    try:
        if "T" in s:
            # `2026-08-26T06:39:10.340Z` — 파이썬이 `Z` 를 못 읽어서 바꿔 준다
            parsed = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=KST)
            return parsed.astimezone(KST).date()
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def to_datetime(v: Any) -> dt.datetime | None:
    """ISO 문자열 → 시간대가 붙은 datetime. 다짐이 주는 `...Z` 를 감싼다."""
    try:
        parsed = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def month_range(year: int, month: int) -> tuple[dt.date, dt.date]:
    """그달 1일과 말일."""
    first = dt.date(year, month, 1)
    last = dt.date(year + (month == 12), (month % 12) + 1, 1) - dt.timedelta(days=1)
    return first, last


def mask_phone(phone: str | None) -> str:
    """`010-****-1234` — 뒤 네 자리만 남긴다.

    사람을 가리는 데는 뒤 네 자리면 충분하고, 화면이 새더라도 그대로 걸 수
    있는 번호가 안 나간다.
    """
    digits = "".join(c for c in (phone or "") if c.isdigit())
    return f"{digits[:3]}-****-{digits[-4:]}" if len(digits) >= 7 else (phone or "-")


def add_day(by_member: dict, key: Any, day: dt.date, *,
            name: str | None, phone: str | None, status: str | None) -> None:
    """회원 한 명의 출석일을 한 칸 채운다 — 두 서비스가 같이 쓰는 자리.

    같은 날 여러 번 찍어도 하루다 (`days` 가 집합이라 저절로 걸러진다).
    """
    m = by_member.setdefault(key, {
        "name": (name or "?").strip() or "?",
        "phone": phone or "",
        "days": set(),
        "status": status or "",
        "last": day,
    })
    m["days"].add(day)
    # 최근 방문 시점의 상태를 남긴다 — 만료 회원인지 가리는 데 쓴다
    if day >= m["last"]:
        m["last"] = day
        if status:
            m["status"] = status
