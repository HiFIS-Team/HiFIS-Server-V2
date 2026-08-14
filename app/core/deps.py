"""공통 의존성 — 현재 사용자 로드 · 권한 가드 (CLAUDE.md §8, §9.1)."""

import hashlib
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException, Query
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.enums import Role
from app.models.staff.employee import Employee

bearer_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Employee:
    payload = decode_token(credentials.credentials, expected_type="access")
    employee = await db.get(Employee, payload.get("sub"))
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(401, detail={"code": "INVALID_TOKEN", "message": "유효하지 않은 사용자입니다"})
    if payload.get("ver", 0) != employee.token_version:  # 로그아웃/비번변경으로 폐기된 세션
        raise HTTPException(401, detail={"code": "TOKEN_REVOKED", "message": "세션이 만료되었어요. 다시 로그인해주세요"})
    return employee


def require_role(*roles: Role) -> Callable[..., Coroutine[Any, Any, Employee]]:
    # MASTER 는 ADMIN 이 할 수 있는 건 전부 승계 — ADMIN 허용 게이트면 MASTER 도 자동 통과.
    # (승인·반려처럼 MASTER 전용으로 막을 곳은 애초에 ADMIN 을 빼고 MASTER 를 명시한다.)
    allowed = set(roles)
    if Role.ADMIN in allowed:
        allowed.add(Role.MASTER)

    async def dependency(user: Employee = Depends(get_current_user)) -> Employee:
        if user.role not in allowed:
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "권한이 없습니다"})
        return user

    return dependency


async def branch_scope(current: Employee = Depends(get_current_user)) -> str | None:
    """목록 지점 스코프 (§0 멀티테넌시) — '지점 업무 데이터'용.

    MASTER·ADMIN 만 전 지점(None). MEMBER·MANAGER 는 본인 소속 지점으로 제한(branch_id 반환).
    → 회원·매출·세션·점수원장·근태·환경정비 등 지점 업무 데이터는 매니저도 자기 지점만 본다.
    ※ '사람(직원 명단·검색)'과 '랭킹'은 전사 인원이 보여야 하므로 이 스코프를 쓰지 않는다.
    """
    if current.role in (Role.MASTER, Role.ADMIN):
        return None
    return current.branch_id


async def branch_filter(
    scope: str | None = Depends(branch_scope),
    branch_id: str | None = Query(None, alias="branchId"),
) -> str | None:
    """볼 지점 — `branch_scope` 에 **고르는 길**을 더한 것.

    앱 업무 화면의 지점 필터가 쓴다. 항목마다 규칙이 갈리면 같은 필터를 걸고도
    화면마다 다른 게 보이므로 판정을 여기 한 곳에 둔다.

    - **MASTER·ADMIN** — `scope` 가 None 이라 고른 지점이 그대로 쓰인다.
      안 고르면(None) 예전처럼 전 지점이다.
    - **MEMBER·MANAGER** — `scope` 가 본인 지점을 주고 **그게 이긴다.**
      `branchId` 를 넣어도 조용히 본인 지점으로 고정된다. 403 을 안 내는 이유는
      남의 지점을 달라고 한 게 아니라 볼 수 있는 만큼만 주는 것이기 때문이다
      (근태 `GET /attendance` 와 같은 규칙 — backend-gap 60).
    """
    return scope or branch_id


async def branch_pick(
    current: Employee = Depends(get_current_user),
    scope: str | None = Depends(branch_scope),
    branch_id: str | None = Query(None, alias="branchId"),
) -> str | None:
    """볼 지점 — **MANAGER 도 고른다.** 지금 쓰는 곳은 `/env-logs` 하나다.

    점장에게 지점을 준 이유가 '다른 지점이 어떻게 하나 보라'는 것인데,
    업무 화면에서 그게 실제로 뜻이 있는 자리는 **환경정비 기록 하나뿐**이다.
    나머지 탭(동료평가·친절도·수업개수·기여도)은 점장에게 **본인 것만**
    보여주는 화면이라, 지점을 걸면 보이던 내 것이 0건이 된다.

    | | 무엇을 쓰나 | 왜 |
    |---|---|---|
    | `/env-logs` | **이 함수** | 다른 지점이 오늘 뭘 했는지 보는 자리 |
    | `/env-items` | `branch_filter` | 누르는 칩이라 늘 본인 지점 (전사면 22개가 겹친다) |
    | 회원·등록권·싸인·친절도·기여도 | `branch_filter`·`branch_scope` | 어차피 본인 것만 그린다 |

    **여는 것은 보는 것뿐이다.** 승인·반려는 MASTER 전용이고 남의 근태·급여는
    MASTER·ADMIN 만 본다 — 그쪽은 각자의 권한 가드가 그대로 막는다.
    이 함수는 그 판단에 손대지 않는다.

    ⚠️ **`branch_scope` 를 열어서 이걸 하면 안 된다.** 그건 아홉 갈래가 같이
    쓰는 공용 스코프라, 한 번 열었더니 환경정비 항목이 22개가 아니라 88개로
    오고 근태에 남의 지점이 섞였다 (실제로 겪었다). 갈래를 나눠서 연다.
    """
    if current.role == Role.MANAGER:
        # 안 고르면 전 지점 — MASTER·ADMIN 과 같은 뜻이 되게 한다
        return branch_id
    return scope or branch_id


# ---------- 지점 출퇴근 단말 ----------
#
# 사람이 아닌 기기가 부르는 길이다. 이 토큰으로 할 수 있는 것은
# `POST /attendance/scan` **하나뿐**이며, 다른 라우터는 이 의존성을 쓰지 않으므로
# 애초에 닿지 않는다 (그쪽은 전부 `get_current_user` 를 탄다).
terminal_scheme = APIKeyHeader(name="X-Terminal-Token", auto_error=False)


def hash_terminal_token(token: str) -> str:
    """원문을 저장하지 않으려고 해시로 찾는다."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class ScanActor:
    """출퇴근 스캔을 요청한 주체 — 사람이거나 지점 단말이다.

    둘의 차이는 **어느 지점까지 찍을 수 있나**와 **사번 없이 본인을 찍을 수
    있나** 둘뿐이라, 엔드포인트가 이 두 값만 보면 된다.
    """

    branch_id: str | None
    #: MASTER·ADMIN 만 참 — 전 지점을 찍을 수 있다
    all_branches: bool
    #: 사람일 때만 채워진다. 단말은 '본인'이 없어서 사번을 반드시 줘야 한다
    employee: Employee | None
    terminal_id: str | None


async def scan_actor(
    terminal_token: str | None = Depends(terminal_scheme),
    credentials: HTTPAuthorizationCredentials | None = Depends(
        HTTPBearer(auto_error=False)
    ),
    db: AsyncSession = Depends(get_db),
) -> ScanActor:
    # 단말 토큰이 있으면 그쪽을 먼저 본다 — 이 헤더를 붙였다는 건 사람이 아니라는 뜻
    if terminal_token:
        from app.models.auth.scan_terminal import ScanTerminal  # 순환 import 방지

        terminal = await db.scalar(
            select(ScanTerminal).where(
                ScanTerminal.token_hash == hash_terminal_token(terminal_token),
                ScanTerminal.revoked_at.is_(None),
            )
        )
        if terminal is None:
            raise HTTPException(
                401,
                detail={"code": "INVALID_TERMINAL", "message": "유효하지 않은 단말입니다"},
            )
        terminal.last_used_at = datetime.now(timezone.utc)
        return ScanActor(
            branch_id=terminal.branch_id,
            all_branches=False,  # 단말은 자기 지점만 — 전 지점을 여는 순간 뜻이 없다
            employee=None,
            terminal_id=terminal.id,
        )

    if credentials is None:
        raise HTTPException(
            401, detail={"code": "UNAUTHORIZED", "message": "인증이 필요합니다"}
        )
    employee = await get_current_user(credentials, db)
    return ScanActor(
        branch_id=employee.branch_id,
        all_branches=employee.role in (Role.MASTER, Role.ADMIN),
        employee=employee,
        terminal_id=None,
    )
