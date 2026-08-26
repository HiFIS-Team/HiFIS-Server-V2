"""브로제이(BroJ) 출석 조회 — 회원 출입 관리 웹에서 그달 출석을 받아 온다.

`broj_test/broj.py` 로 확인한 흐름을 그대로 옮겼다. 인증은 v1 서버
(`HiFIS-Server/app/services/broj.py`) 와 같다.

    1) POST /BroJServer/joauth/login   (form: member_id / member_password)
           → {"result": {"access_token": ...}}
    2) 이후 모든 호출에 헤더 두 개
           Authorization:              Bearer <access_token>
           X-Broj-Jgroup-Access-Token: <jgroup_token>

**`jgroup_token` 은 로그인으로 안 받아진다.** 브라우저 네트워크탭에서 복사해
`.env` 에 넣는 값이라, 만료되면 출석 조회가 통째로 막힌다. 다시 복사해 넣어야 한다.

## 화순점만이다

브로제이를 쓰는 지점이 화순뿐이라 그룹 키가 하나다. 지점별로 나누는 코드를
두지 않았다 — 다른 지점이 붙게 되면 그때 키를 여러 개로 늘린다.

## 왜 우리 DB 에 안 쌓나

한 달치가 5천여 건인데 **화면에 뜨는 건 걸러낸 수십 명**이고, 보는 사람도
직원 몇이다. 표를 새로 만들고 잡을 돌리는 값보다, 받아서 걸러 **잠깐 들고
있는** 편이 작고 항상 최신이다. 대신 서버를 재기동하면 캐시가 빈다.
"""

import asyncio
import datetime as dt
import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.periods import KST

logger = logging.getLogger(__name__)

BASE = "https://brojserver.broj.co.kr/BroJServer"
LOGIN_URL = f"{BASE}/joauth/login"

#: 관리자 웹 '출석 현황' 화면이 쓰는 그 요청
ATTENDANCE_PATH = "/read/v1/admin/groups/{jgroup_key}/attendance/histories"

PAGE_SIZE = 500

#: 한 번에 넘길 페이지 수 상한 — 안 걸면 응답이 계속 꽉 찰 때 영영 돈다.
#: 한 달 5천여 건이라 11페이지쯤인데, 늘어날 여지를 두고 잡았다.
MAX_PAGES = 40

#: 받아 둔 결과를 들고 있는 시간(초).
#:
#: 출석은 사람이 문을 지날 때 한 건씩 늘어난다. 5분 지난 값을 보는 것이
#: 페이지를 열 때마다 브로제이를 11번 치는 것보다 낫다.
CACHE_TTL = 300

#: 실제 입장만 센다. `EXPIRED_TICKET` 은 만료된 회원권으로 찍어서 **입장이 안 된**
#: 기록이라, 세면 안 온 사람이 온 것으로 잡힌다.
OK_STATUS = "SUCCESS"

_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = asyncio.Lock()


class BrojError(RuntimeError):
    """브로제이가 못 준다 — 자격증명 만료·장애 등. 화면이 이걸 잡아 안내한다."""


def configured() -> bool:
    """자격증명이 다 있나 — 하나라도 비면 조회를 시도하지 않는다.

    APNs·FCM 과 같은 규칙이다. 다만 저쪽은 조용히 넘어가는데(알림은 못 가도
    앱이 돌아야 한다) 여기는 **화면이 그것 하나뿐**이라 에러를 올린다.
    """
    return all(
        (
            settings.broj_login_id,
            settings.broj_login_pw,
            settings.broj_jgroup_token,
            settings.broj_jgroup_key,
        )
    )


async def _login(client: httpx.AsyncClient) -> str:
    r = await client.post(
        LOGIN_URL,
        data={
            "member_id": settings.broj_login_id,
            "member_password": settings.broj_login_pw,
        },
    )
    r.raise_for_status()
    token = (r.json().get("result") or {}).get("access_token")
    if not token:
        raise BrojError("브로제이 로그인 응답에 access_token 이 없습니다")
    return token


def _rows_from(payload: Any) -> list[dict]:
    """응답에서 레코드 목록을 꺼낸다 — 브로제이가 `result` 로 감싸 준다.

    감싸는 이름이 화면마다 조금씩 다른 것을 v1 때부터 봐서, 몇 가지를 훑는다.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("result", "content", "list", "data", "items"):
            v = payload.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                inner = _rows_from(v)
                if inner:
                    return inner
    return []


async def _fetch(start: dt.date, end: dt.date) -> list[dict]:
    """기간 전체 출석 이력.

    **페이지를 끝까지 돈다.** 한 장만 받으면 500건에서 잘린 채로 세게 되고,
    잘린 뒷부분 회원은 아예 안 온 것처럼 보인다.
    """
    path = ATTENDANCE_PATH.replace("{jgroup_key}", settings.broj_jgroup_key)
    rows: list[dict] = []

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        token = await _login(client)
        for page in range(MAX_PAGES):
            params = {
                "size": PAGE_SIZE,
                "page_index": page,
                "start_date": str(start),
                "end_date": str(end),
                "filter.member_type": "ALL",
                "filter.attendance_status": "ALL",
            }
            for attempt in (1, 2):
                r = await client.get(
                    BASE + path,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Broj-Jgroup-Access-Token": settings.broj_jgroup_token,
                    },
                    params=params,
                )
                # 토큰이 만료됐을 수 있다 — 한 번만 다시 받아 본다 (v1 과 같은 동작)
                if r.status_code == 401 and attempt == 1:
                    token = await _login(client)
                    continue
                break
            if r.status_code >= 400:
                raise BrojError(f"브로제이 출석 조회 실패 (HTTP {r.status_code})")

            got = _rows_from(r.json())
            rows.extend(got)
            if len(got) < PAGE_SIZE:
                break
        else:
            logger.warning(
                "브로제이 출석: %d페이지까지 받았는데도 계속 꽉 찹니다 — 잘렸을 수 있습니다",
                MAX_PAGES,
            )
    return rows


async def attendance_rows(start: dt.date, end: dt.date) -> list[dict]:
    """그 기간 출석 원본 — [CACHE_TTL] 초 동안 들고 있는다.

    **락으로 묶는다.** 안 묶으면 여러 명이 동시에 열었을 때 각자 11페이지씩
    받아서 브로제이를 그만큼 두들긴다.
    """
    key = f"{start}~{end}"
    now = time.monotonic()

    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]

    async with _lock:
        # 기다리는 사이 다른 요청이 채웠을 수 있다
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return hit[1]
        rows = await _fetch(start, end)
        _cache[key] = (time.monotonic(), rows)
    return rows


def to_date(v: Any) -> dt.date | None:
    """브로제이가 뭘로 주든 날짜로 — ms 타임스탬프 · ISO · `YYYYMMDD`.

    **타임스탬프는 KST 로 환산한다.** UTC 로 하면 오전 9시 이전 출석이 전날로
    밀려서, 일찍 오는 회원의 출석일이 하루씩 어긋난다.
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
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def summarize(rows: list[dict]) -> dict[Any, dict]:
    """회원별로 출석일을 모은다 — `{회원키: {name, phone, days, status, last}}`.

    **직원 출근을 뺀다.** `member_type == "ADMIN"` 은 직원이 문을 지난 기록이라
    회원 출석이 아니다. 안 빼면 직원이 늘 1등이다.

    같은 날 여러 번 찍어도 하루다 — `days` 가 집합이라 저절로 걸러진다.
    """
    by_member: dict[Any, dict] = {}
    for row in rows:
        if row.get("member_type") != "CUSTOMER":
            continue
        if row.get("attendance_status") != OK_STATUS:
            continue
        day = to_date(row.get("attendance_date"))
        if day is None:
            continue

        key = row.get("group_member_key")
        m = by_member.setdefault(
            key,
            {
                "name": row.get("name") or "?",
                "phone": row.get("phone") or "",
                "days": set(),
                "status": row.get("customer_status") or "",
                "last": day,
            },
        )
        m["days"].add(day)
        # 최근 방문 시점의 회원 상태를 남긴다 — 만료 회원인지 가리는 데 쓴다
        if day >= m["last"]:
            m["last"] = day
            m["status"] = row.get("customer_status") or m["status"]
    return by_member


def mask_phone(phone: str) -> str:
    """`010-****-1234` — 뒤 네 자리만 남긴다.

    사람을 가리는 데는 뒤 네 자리면 충분하고, 화면이 새더라도 그대로 걸 수 있는
    번호가 안 나간다.
    """
    digits = "".join(c for c in phone if c.isdigit())
    return f"{digits[:3]}-****-{digits[-4:]}" if len(digits) >= 7 else phone


def month_range(year: int, month: int) -> tuple[dt.date, dt.date]:
    """그달 1일과 말일."""
    first = dt.date(year, month, 1)
    last = dt.date(year + (month == 12), (month % 12) + 1, 1) - dt.timedelta(days=1)
    return first, last
