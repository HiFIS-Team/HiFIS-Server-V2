"""공통 의존성 — 현재 사용자 로드 · 권한 가드 (CLAUDE.md §8, §9.1)."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.enums import Role
from app.models.employee import Employee

bearer_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Employee:
    payload = decode_token(credentials.credentials, expected_type="access")
    employee = await db.get(Employee, payload.get("sub"))
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(401, detail={"code": "INVALID_TOKEN", "message": "유효하지 않은 사용자입니다"})
    return employee


def require_role(*roles: Role) -> Callable[..., Coroutine[Any, Any, Employee]]:
    async def dependency(user: Employee = Depends(get_current_user)) -> Employee:
        if user.role not in roles:
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "권한이 없습니다"})
        return user

    return dependency


async def branch_scope(current: Employee = Depends(get_current_user)) -> str | None:
    """목록 지점 스코프 (§0 멀티테넌시).

    MEMBER 는 본인 소속 지점으로 제한(branch_id 반환), MANAGER/ADMIN 은 전체(None).
    """
    if current.role == Role.MEMBER:
        return current.branch_id
    return None
