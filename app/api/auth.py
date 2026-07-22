"""Auth 라우터 — 로그인 · 리프레시 · 로그아웃 · 내 정보 (CLAUDE.md §2.3).

TODO: signup + InviteKey/JoinRequest 는 다음 단계에서 추가.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.db.session import get_db
from app.models.employee import Employee
from app.schemas.auth import AccessTokenResponse, LoginRequest, RefreshRequest, TokenResponse
from app.schemas.employee import EmployeeOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(
        select(Employee).where(Employee.email == payload.email, Employee.deleted_at.is_(None))
    )
    employee = result.scalar_one_or_none()
    if employee is None or not verify_password(payload.password, employee.password_hash):
        raise HTTPException(
            401, detail={"code": "INVALID_CREDENTIALS", "message": "이메일 또는 비밀번호가 올바르지 않습니다"}
        )
    return TokenResponse(
        access_token=create_access_token(employee.id),
        refresh_token=create_refresh_token(employee.id),
        employee=EmployeeOut.model_validate(employee),
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> AccessTokenResponse:
    data = decode_token(payload.refresh_token, expected_type="refresh")
    employee = await db.get(Employee, data.get("sub"))
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(401, detail={"code": "INVALID_TOKEN", "message": "유효하지 않은 사용자입니다"})
    return AccessTokenResponse(access_token=create_access_token(employee.id))


@router.post("/logout", status_code=204)
async def logout(_: Employee = Depends(get_current_user)) -> None:
    # TODO: refresh 토큰 블록리스트(Redis/DB) 무효화 — §9.1
    return None


@router.get("/me", response_model=EmployeeOut)
async def me(user: Employee = Depends(get_current_user)) -> Employee:
    return user
