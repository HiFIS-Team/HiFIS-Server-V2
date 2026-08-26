"""다짐(Dagym) 출석 조회 — 첨단·동광주가 쓰는 회원 관리 웹.

`broj_test/dajim.py` 로 확인한 흐름을 그대로 옮겼다. 인증은 v1 서버
(`HiFIS-Server/app/services/dajim.py`) 와 같다.

    1) mutation Login(email, password)   ← 비번은 평문이 아니라 **SHA-256 hex**
           → data.loginAccount.token (JWT)
    2) 이후 호출 헤더 셋
           authorization: <token>     ← **Bearer 를 안 붙인다** (다짐 방식)
           app-type:      managerPC
           x-gym-id:      <지점별 gym_id>

## 브로제이와 다른 것 넷

1. **GraphQL 한 주소다.** 에러도 HTTP 200 으로 오므로 본문의 `errors` 를 봐야 한다
2. **지점마다 gym_id 가 다르다** — `branches.dajim_gym_id` 에 있다
3. **브라우저 UA 가 없으면 403** 이다 (`허용되지 않은 접근입니다`).
   v1 에는 이 헤더가 없다 — 그때는 통했지만 지금은 막힌다
4. **회원 상태 칸이 없다.** 브로제이의 `customer_status` 에 해당하는 값이 없어서
   '적게 나온' 목록에서 만료 회원을 갈라낼 수 없다 — 상태를 빈 값으로 둔다

## 직원을 어떻게 빼나

다짐에는 '직원' 표시가 없다. 대신 **직원은 회원권이 사실상 무기한**으로 들어가
있다 (만료가 2107~2109년). 일반 회원 중 제일 긴 것이 5년 남짓이고 그 위로는
뚝 끊겨서, **만료까지 10년을 넘으면 직원**으로 본다.

계정이 둘인 직원도 있다 (탈퇴시킨 옛 계정 + 지금 직원권 계정). 옛 계정은
회원 목록에서 빠져 만료일로 못 거르므로 **이름으로 보완**한다. 동명이인일
수도 있어서 몇 명을 그렇게 걸렀는지 로그에 남긴다.
"""

import datetime as dt
import hashlib
import logging

import httpx

from app.core.config import settings
from app.services.gym_history import HistoryError, add_day, to_date, to_datetime

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://www.dagym-manager.com/api/graphql"

#: 브라우저에서 온 것처럼 보여야 한다 — 없으면 403 이다
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {
    "app-type": "managerPC",
    "content-type": "application/json",
    "user-agent": _USER_AGENT,
    "origin": "https://www.dagym-manager.com",
    "referer": "https://www.dagym-manager.com/",
}

PAGE_SIZE = 1000

#: 한 번에 넘길 페이지 수 상한 — 안 걸면 응답이 계속 차 있을 때 영영 돈다.
#: 동광주 한 달이 2만 9천 건(30페이지)이라 넉넉히 잡았다.
MAX_PAGES = 60

#: 인정할 입장 상태. `fail` 은 문이 안 열린 기록이라 세면 안 온 사람이 온 것이 된다.
OK_STATUS = "success"

#: 만료까지 이 햇수를 넘으면 직원으로 본다 (위 '직원을 어떻게 빼나' 참고)
STAFF_YEARS = 10.0

_LOGIN = """mutation Login($email: String!, $password: String!) {
  loginAccount(email: $email, password: $password) { status token }
}"""

_ENTRIES = """query EntryHistories(
  $filter: EntryHistoryFilterInput!, $limit: Int, $offset: Int
) {
  entryHistories(filter: $filter, limit: $limit, offset: $offset) {
    count
    data { id entryAt status user { id name phone } }
  }
}"""

_MEMBERS = """query ManagerMemberList(
  $filter: ManagerMemberListFilterInput!, $paging: PagingInput!
) {
  managerMembers {
    list(filter: $filter, paging: $paging) {
      count
      data { id name phone expiredAt createdAt }
    }
  }
}"""


def configured() -> bool:
    """자격증명이 다 있나 — 하나라도 비면 조회를 시도하지 않는다."""
    return bool(settings.dajim_login_email and settings.dajim_login_pw)


class _Client:
    """한 번 쓰고 버리는 세션 — 지점 하나를 받는 동안만 산다."""

    def __init__(self, http: httpx.AsyncClient, gym_id: str) -> None:
        self.http = http
        self.gym_id = gym_id
        self.token: str | None = None

    async def login(self) -> str:
        # **비번을 그대로 보내지 않는다** — 다짐이 SHA-256 hex 를 받는다
        pw = hashlib.sha256(settings.dajim_login_pw.encode("utf-8")).hexdigest()
        r = await self.http.post(
            GRAPHQL_URL,
            json={
                "operationName": "Login",
                "query": _LOGIN,
                "variables": {"email": settings.dajim_login_email, "password": pw},
            },
            headers=_BASE_HEADERS,
        )
        r.raise_for_status()
        body = r.json()
        if "errors" in body:
            raise HistoryError("다짐 로그인이 거부됐습니다")
        res = (body.get("data") or {}).get("loginAccount") or {}
        if res.get("status") != "SUCCESS" or not res.get("token"):
            raise HistoryError("다짐 로그인 실패 — 계정을 확인해 주세요")
        self.token = res["token"]
        return self.token

    async def gql(self, query: str, variables: dict, op: str) -> dict:
        """401·403 이면 다시 로그인하고 한 번만 재시도한다."""
        if self.token is None:
            await self.login()
        payload = {"operationName": op, "query": query, "variables": variables}

        for attempt in (1, 2):
            r = await self.http.post(
                GRAPHQL_URL,
                json=payload,
                headers={
                    **_BASE_HEADERS,
                    "authorization": self.token or "",  # Bearer 를 안 붙인다
                    "x-gym-id": self.gym_id,
                },
            )
            if r.status_code in (401, 403) and attempt == 1:
                await self.login()
                continue
            break

        if r.status_code >= 400:
            raise HistoryError(f"다짐 조회 실패 (HTTP {r.status_code})")
        body = r.json()
        # **에러도 200 으로 온다** — 여기를 안 보면 빈 목록을 정상으로 착각한다
        if "errors" in body:
            first = (body["errors"] or [{}])[0].get("message", "")
            raise HistoryError(f"다짐 조회 오류: {first[:120]}")
        return body.get("data") or {}


async def _entries(c: _Client, start: dt.date, end: dt.date) -> list[dict]:
    """기간 전체 입장 이력 — `offset` 을 끝까지 민다."""
    rows: list[dict] = []
    total: int | None = None
    for _ in range(MAX_PAGES):
        data = await c.gql(
            _ENTRIES,
            {
                "filter": {"startAt": str(start), "endAt": str(end)},
                "limit": PAGE_SIZE,
                "offset": len(rows),
            },
            "EntryHistories",
        )
        eh = data.get("entryHistories") or {}
        if total is None:
            total = eh.get("count")
        got = eh.get("data") or []
        rows.extend(got)
        if not got or len(rows) >= (total or 0):
            break
    else:
        logger.warning("다짐 입장 이력: %d페이지까지 받았는데도 안 끝납니다", MAX_PAGES)
    return rows


async def _members(c: _Client) -> list[dict]:
    """지점 전체 회원 목록 — 직원을 가려내는 데만 쓴다."""
    rows: list[dict] = []
    for _ in range(MAX_PAGES):
        data = await c.gql(
            _MEMBERS,
            {"filter": {}, "paging": {"limit": PAGE_SIZE, "offset": len(rows)}},
            "ManagerMemberList",
        )
        lst = (data.get("managerMembers") or {}).get("list") or {}
        got = lst.get("data") or []
        rows.extend(got)
        if not got or len(rows) >= (lst.get("count") or 0):
            break
    return rows


def _staff(members: list[dict]) -> tuple[set[str], set[str]]:
    """(직원 id 집합, 직원 이름 집합) — 만료까지 [STAFF_YEARS] 를 넘는 회원."""
    ids: set[str] = set()
    names: set[str] = set()
    for r in members:
        made, ends = to_datetime(r.get("createdAt")), to_datetime(r.get("expiredAt"))
        if made is None or ends is None:
            continue
        if (ends - made).days / 365.25 > STAFF_YEARS:
            ids.add(r["id"])
            if r.get("name"):
                names.add(r["name"].strip())
    return ids, names


def _ghost_staff(rows: list[dict], members: list[dict], names: set[str]) -> dict[str, str]:
    """회원 목록엔 없는데 출석엔 있고, 직원과 이름이 같은 계정.

    직원이 계정을 둘 갖고 있는 경우다 (탈퇴시킨 옛 계정 + 지금 직원권 계정).
    옛 계정은 목록에서 빠져 만료일로 못 거르므로 이름으로 보완한다.
    """
    known = {m["id"] for m in members}
    out: dict[str, str] = {}
    for r in rows:
        u = r.get("user") or {}
        uid, name = u.get("id"), (u.get("name") or "").strip()
        if uid and uid not in known and name in names:
            out[uid] = name
    return out


async def summarize(gym_id: str, start: dt.date, end: dt.date) -> dict[str, dict]:
    """회원별 출석일 — `{user_id: {name, phone, days, status, last}}`.

    직원은 뺀다. 안 빼면 직원이 늘 1등이다 (매일 문을 지난다).
    """
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as http:
        c = _Client(http, gym_id)
        rows = await _entries(c, start, end)
        if not rows:
            return {}
        members = await _members(c)

    exclude, names = _staff(members)
    ghosts = _ghost_staff(rows, members, names)
    exclude |= set(ghosts)
    if ghosts:
        logger.info("다짐 %s: 이름으로 함께 뺀 직원 계정 %d개", gym_id[:8], len(ghosts))

    by_member: dict[str, dict] = {}
    for row in rows:
        if row.get("status") != OK_STATUS:
            continue
        day = to_date(row.get("entryAt"))
        if day is None:
            continue
        u = row.get("user") or {}
        uid = u.get("id")
        if not uid or uid in exclude:
            continue
        # 다짐에는 회원 상태 칸이 없다 — 빈 값으로 둔다
        add_day(by_member, uid, day, name=u.get("name"), phone=u.get("phone"), status=None)
    return by_member
