"""공통 의존성 — 현재 사용자 로드 · 권한 가드 (CLAUDE.md §8, §9.1)."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
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
