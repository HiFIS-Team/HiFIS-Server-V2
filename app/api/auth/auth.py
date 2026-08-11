"""Auth 라우터 — 로그인 · 리프레시 · 로그아웃 · 회원가입 · 내 정보 (CLAUDE.md §2.3)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.ratelimit import client_key, limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.enums import AccessEvent, InviteStatus
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.models.auth.invite import InviteKey
from app.models.platform.access_log import AccessLog
from app.schemas.auth.auth import (
    AccessTokenResponse,
    LoginRequest,
    PasswordResetConfirmReq,
    PasswordResetRequestReq,
    PasswordResetVerifyReq,
    PasswordResetVerifyResp,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
)
from app.schemas.staff.employee import EmployeeOut
from app.services import notification_texts as ntext
from app.services.avatar import next_avatar_color
from app.services.employee_codes import unique_emp_no
from app.services.notifications import notify_bosses
from app.services.password_reset import consume_reset_token, issue_code, normalize_contact, verify_code

router = APIRouter(prefix="/auth", tags=["auth"])

# 로그인 타이밍 오라클 방지 — 사용자가 없어도 더미 해시로 verify 를 돌려 응답시간을 균일화
_DUMMY_HASH = hash_password("timing-equalizer-placeholder")


@router.post("/signup", response_model=SignupResponse, status_code=201)
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)) -> SignupResponse:
    if (await db.execute(select(Employee).where(Employee.email == payload.email))).scalar_one_or_none():
        raise HTTPException(409, detail={"code": "EMAIL_TAKEN", "message": "이미 사용 중인 이메일입니다"})

    # 회원가입은 유효한 초대키 필수 → 즉시 가입 (승인 대기 흐름 폐지)
    key = (
        await db.execute(select(InviteKey).where(InviteKey.code == payload.invite_key))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if key is None or key.status != InviteStatus.UNUSED or key.expires_at <= now:
        raise HTTPException(400, detail={"code": "INVALID_INVITE_KEY", "message": "유효하지 않은 초대키입니다"})
    employee = Employee(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        branch_id=key.branch_id,
        role=key.role,
        rank=key.rank,
        # 알바로 뽑았으면 알바로 들어온다. 들어온 뒤 정규직으로 올리거나
        # 퇴사시키는 건 대표(MASTER)가 `PATCH /employees/{id}` 로 판단한다.
        employment_type=key.employment_type,
        team=key.team,
        emp_no=await unique_emp_no(db),
        avatar_color=await next_avatar_color(db),  # 팔레트 분산 배정(§2.2)
    )
    key.status = InviteStatus.USED
    db.add(employee)
    # 대표·관리자에게 알린다 (2026-08-11 대표 요청) — 초대키를 준 사람이 실제로
    # 들어왔는지는 조직도를 열어 봐야만 알 수 있었다.
    branch = await db.get(Branch, employee.branch_id) if employee.branch_id else None
    await notify_bosses(
        db,
        **ntext.employee_joined(
            employee.name,
            branch.name if branch else None,
            ntext.rank_label(employee.rank),
        ),
    )
    await db.commit()
    return SignupResponse(result="JOINED")


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")  # IP당 분 10회 — 무차별 대입 방지(§M4)
async def login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    ip = client_key(request)  # 프록시(Caddy/CF) 뒤에선 X-Forwarded-For 첫 홉
    user_agent = (request.headers.get("user-agent") or "")[:300]
    result = await db.execute(
        select(Employee).where(Employee.email == payload.email, Employee.deleted_at.is_(None))
    )
    employee = result.scalar_one_or_none()
    # 사용자 유무와 무관하게 항상 verify 실행(단락 평가로 인한 타이밍 노출 방지)
    password_ok = verify_password(payload.password, employee.password_hash if employee else _DUMMY_HASH)
    if employee is None or not password_ok:
        db.add(AccessLog(  # 실패도 기록(무차별 대입·이상 접근 모니터링, §8)
            employee_id=employee.id if employee else None,
            email=payload.email,
            event=AccessEvent.LOGIN_FAIL,
            ip=ip,
            user_agent=user_agent,
        ))
        await db.commit()
        raise HTTPException(
            401, detail={"code": "INVALID_CREDENTIALS", "message": "이메일 또는 비밀번호가 올바르지 않습니다"}
        )
    # 응답을 커밋 전에 만들어 둔다(순서 무관 — expire_on_commit=False 지만 명시적으로 안전하게)
    response = TokenResponse(
        access_token=create_access_token(employee.id, employee.token_version),
        refresh_token=create_refresh_token(employee.id, employee.token_version),
        employee=EmployeeOut.model_validate(employee),
    )
    db.add(AccessLog(
        employee_id=employee.id,
        email=employee.email,
        event=AccessEvent.LOGIN_SUCCESS,
        ip=ip,
        user_agent=user_agent,
    ))
    await db.commit()
    return response


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> AccessTokenResponse:
    data = decode_token(payload.refresh_token, expected_type="refresh")
    employee = await db.get(Employee, data.get("sub"))
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(401, detail={"code": "INVALID_TOKEN", "message": "유효하지 않은 사용자입니다"})
    if data.get("ver", 0) != employee.token_version:  # 폐기된 refresh 토큰
        raise HTTPException(401, detail={"code": "TOKEN_REVOKED", "message": "세션이 만료되었어요. 다시 로그인해주세요"})
    return AccessTokenResponse(access_token=create_access_token(employee.id, employee.token_version))


@router.post("/logout", status_code=204)
async def logout(
    user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    user.token_version += 1  # 이 계정의 기존 access·refresh 토큰 전부 무효화(§M2)
    await db.commit()
    return None


@router.get("/me", response_model=EmployeeOut)
async def me(user: Employee = Depends(get_current_user)) -> Employee:
    return user


# --- 비밀번호 재설정 (비로그인) — 3단계 (CLAUDE.md §2.3) ---
@router.post("/password-reset/request", status_code=200)
@limiter.limit("5/minute")  # IP당 분 5회 — 스팸/열거 방지
async def password_reset_request(
    request: Request, payload: PasswordResetRequestReq, db: AsyncSession = Depends(get_db)
) -> dict:
    method, contact = normalize_contact(payload.contact)
    if method == "EMAIL":
        emp = (
            await db.execute(select(Employee).where(Employee.email == contact, Employee.deleted_at.is_(None)))
        ).scalar_one_or_none()
    else:
        emp = (
            await db.execute(select(Employee).where(Employee.phone == contact, Employee.deleted_at.is_(None)))
        ).scalar_one_or_none()
    # 대상 유무와 무관하게 항상 성공 응답(사용자 열거 방지). 존재하면 인증번호 발송.
    if emp is not None:
        await issue_code(payload.contact, emp.id)
    return {"ok": True}


@router.post("/password-reset/verify", response_model=PasswordResetVerifyResp)
@limiter.limit("10/minute")
async def password_reset_verify(
    request: Request, payload: PasswordResetVerifyReq
) -> PasswordResetVerifyResp:
    reset_token = await verify_code(payload.contact, payload.code)
    if reset_token is None:
        raise HTTPException(400, detail={"code": "INVALID_CODE", "message": "인증번호가 올바르지 않거나 만료되었습니다"})
    return PasswordResetVerifyResp(reset_token=reset_token)


@router.post("/password-reset/confirm", status_code=204)
async def password_reset_confirm(
    payload: PasswordResetConfirmReq, db: AsyncSession = Depends(get_db)
) -> None:
    employee_id = await consume_reset_token(payload.reset_token)
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(400, detail={"code": "INVALID_RESET_TOKEN", "message": "재설정 토큰이 유효하지 않습니다"})
    employee.password_hash = hash_password(payload.password)
    employee.token_version += 1  # 재설정 시 기존 세션 전부 무효화(§M2)
    await db.commit()
    return None
