"""Auth 라우터 — 로그인 · 리프레시 · 로그아웃 · 회원가입 · 내 정보 (CLAUDE.md §2.3)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.enums import InviteStatus, JoinRequestStatus
from app.models.org.employee import Employee
from app.models.org.invite import InviteKey
from app.models.org.join_request import JoinRequest
from app.schemas.org.auth import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
)
from app.schemas.org.employee import EmployeeOut
from app.services.employee_codes import unique_emp_no

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse, status_code=201)
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)) -> SignupResponse:
    if (await db.execute(select(Employee).where(Employee.email == payload.email))).scalar_one_or_none():
        raise HTTPException(409, detail={"code": "EMAIL_TAKEN", "message": "이미 사용 중인 이메일입니다"})

    # 유효 초대키 → 즉시 가입 (JOINED)
    if payload.invite_key:
        key = (
            await db.execute(select(InviteKey).where(InviteKey.code == payload.invite_key))
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if key is None or key.status != InviteStatus.UNUSED or key.expires_at <= now:
            raise HTTPException(400, detail={"code": "INVALID_INVITE_KEY", "message": "유효하지 않은 초대키입니다"})
        employee = Employee(
            name=payload.name,
            email=payload.email,
            password_hash=hash_password(payload.password),
            branch_id=key.branch_id,
            role=key.role,
            rank=key.rank,
            team=key.team,
            emp_no=await unique_emp_no(db),
        )
        key.status = InviteStatus.USED
        db.add(employee)
        await db.commit()
        return SignupResponse(result="JOINED")

    # 초대키 없음 → 승인 대기 (PENDING)
    pending = (
        await db.execute(
            select(JoinRequest).where(
                JoinRequest.email == payload.email,
                JoinRequest.status == JoinRequestStatus.PENDING,
            )
        )
    ).scalar_one_or_none()
    if pending:
        raise HTTPException(409, detail={"code": "JOIN_REQUEST_PENDING", "message": "이미 승인 대기 중입니다"})
    db.add(
        JoinRequest(
            name=payload.name,
            email=payload.email,
            password_hash=hash_password(payload.password),
        )
    )
    await db.commit()
    return SignupResponse(result="PENDING")


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
