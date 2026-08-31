"""Auth 라우터 — 로그인 · 리프레시 · 로그아웃 · 회원가입 · 내 정보 (CLAUDE.md §2.3)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.staff.employees import SUSPEND_DEFAULT_REASON
from app.core.deps import ensure_not_locked, get_current_user
from app.core.ratelimit import client_key, limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.enums import AccessEvent, EmployeeStatus, InviteStatus
from app.models.legal.consent import EmployeeConsent
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
from app.ws.manager import manager

router = APIRouter(prefix="/auth", tags=["auth"])

# 로그인 타이밍 오라클 방지 — 사용자가 없어도 더미 해시로 verify 를 돌려 응답시간을 균일화
_DUMMY_HASH = hash_password("timing-equalizer-placeholder")

#: 가입에 반드시 있어야 하는 동의 — 하나라도 빠지면 계정을 안 만든다
_REQUIRED_CONSENTS = {"TERMS", "PRIVACY"}


@router.post("/signup", response_model=SignupResponse, status_code=201)
@limiter.limit("20/minute")  # IP당 분 20회 — 초대키 대입·가입 스팸 방지
async def signup(
    request: Request, payload: SignupRequest, db: AsyncSession = Depends(get_db)
) -> SignupResponse:
    given = {c.doc_type for c in payload.consents}
    # 보냈으면 둘 다 있어야 한다. 아예 안 보낸 건 구버전 앱이라 통과시킨다
    # (그쪽은 가입 직후 `POST /employees/me/consents` 로 따로 남긴다).
    if given and not _REQUIRED_CONSENTS.issubset(given):
        raise HTTPException(
            400, detail={"code": "CONSENT_REQUIRED", "message": "이용약관과 개인정보 처리방침에 동의해야 가입할 수 있습니다"}
        )
    if (await db.execute(select(Employee).where(Employee.email == payload.email))).scalar_one_or_none():
        raise HTTPException(409, detail={"code": "EMAIL_TAKEN", "message": "이미 사용 중인 이메일입니다"})

    # 회원가입은 유효한 초대키 필수 → 즉시 가입 (승인 대기 흐름 폐지)
    #
    # **행을 잠근다.** 잠그지 않으면 같은 초대키로 동시에 들어온 두 요청이 둘 다
    # UNUSED 를 읽고 둘 다 통과해 계정이 두 개 생긴다 (1회용이라는 전제가 깨진다).
    key = (
        await db.execute(
            select(InviteKey).where(InviteKey.code == payload.invite_key).with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if key is None or key.status != InviteStatus.UNUSED or key.expires_at <= now:
        raise HTTPException(400, detail={"code": "INVALID_INVITE_KEY", "message": "유효하지 않은 초대키입니다"})
    # 대표 전용 잠금 중에는 새 계정도 안 만든다 — 잠가 놓고 초대키로 들어와
    # 자리를 잡는 길이 열려 있으면 잠근 의미가 없다(초대키는 1회용 소진도 된다)
    ensure_not_locked(key.role)
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
    await db.flush()  # employee.id 확보 — 동의 이력이 이걸 참조한다
    ip = client_key(request)[:64]
    for agreement in payload.consents:
        db.add(
            EmployeeConsent(
                employee_id=employee.id,
                doc_type=agreement.doc_type,
                doc_version=agreement.doc_version,
                ip=ip,
            )
        )
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
    try:
        await db.commit()
    except IntegrityError:  # 같은 이메일이 동시에 들어온 경우 — 유니크 제약이 최종 판정
        await db.rollback()
        raise HTTPException(409, detail={"code": "EMAIL_TAKEN", "message": "이미 사용 중인 이메일입니다"})
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
    # 계정 정지 — **비밀번호는 맞았지만** 막는다 (이용약관 제8조 1항).
    # 사유를 그대로 돌려줘서 로그인 화면에 뜬다. 왜 막혔는지 모르면
    # 본인은 고장으로 읽고, 풀 방법도 알 수 없다.
    if employee.suspended_at is not None:
        db.add(AccessLog(  # 정지된 계정의 시도도 남긴다
            employee_id=employee.id,
            email=payload.email,
            event=AccessEvent.LOGIN_FAIL,
            ip=ip,
            user_agent=user_agent,
        ))
        await db.commit()
        raise HTTPException(
            403,
            detail={
                "code": "ACCOUNT_SUSPENDED",
                "message": employee.suspend_reason or SUSPEND_DEFAULT_REASON,
            },
        )

    # 퇴사 — **비밀번호는 맞았지만** 막는다 (2026-08-19).
    #
    # 예전에는 `deleted_at` 만 봐서, 조직도의 `퇴사 처리`(= `status` 만 바꾼다)로
    # 내보낸 사람이 **다시 로그인하면 그냥 들어왔다.** 나간 사람이 급여·조직도·
    # 공지·사내톡을 그대로 봤다. 퇴사 시각에 세션을 끊어도 다시 받아 가면 그만이라
    # 여기를 막아야 실제로 끊긴다.
    #
    # **복직은 영향이 없다** — `ACTIVE` 로 되돌리면 바로 다시 된다.
    # 탈퇴(`DELETE`)는 `deleted_at` 이 서서 위에서 이미 걸린다.
    if employee.status == EmployeeStatus.RESIGNED:
        db.add(AccessLog(
            employee_id=employee.id,
            email=payload.email,
            event=AccessEvent.LOGIN_FAIL,
            ip=ip,
            user_agent=user_agent,
        ))
        await db.commit()
        raise HTTPException(
            403,
            detail={
                "code": "ACCOUNT_RESIGNED",
                "message": "퇴사 처리된 계정입니다.\n문의는 대표에게 해 주세요.",
            },
        )

    # 대표 전용 잠금 — **비밀번호는 맞았지만** 지금은 못 들어간다.
    # 로그인 성공으로 안 남긴다 (실제로 세션이 안 생겼다)
    ensure_not_locked(employee.role)

    # 처음 들어온 순간을 한 번만 찍는다 — 프로필 상세의 '첫 접속일' (2026-08-13).
    # **응답을 만들기 전에** 세워야 그 자리에서 바로 값이 실린다.
    if employee.first_login_at is None:
        employee.first_login_at = datetime.now(timezone.utc)

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
@limiter.limit("60/minute")  # 넉넉하게 — 실사용자가 걸리면 로그아웃되는 자리다
async def refresh(
    request: Request, payload: RefreshRequest, db: AsyncSession = Depends(get_db)
) -> AccessTokenResponse:
    data = decode_token(payload.refresh_token, expected_type="refresh")
    employee = await db.get(Employee, data.get("sub"))
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(401, detail={"code": "INVALID_TOKEN", "message": "유효하지 않은 사용자입니다"})
    if data.get("ver", 0) != employee.token_version:  # 폐기된 refresh 토큰
        raise HTTPException(401, detail={"code": "TOKEN_REVOKED", "message": "세션이 만료되었어요. 다시 로그인해주세요"})
    # 잠겨 있으면 새 access 도 안 준다 — 안 막으면 켜 둔 앱이 계속 갱신해 쓴다
    ensure_not_locked(employee.role)
    return AccessTokenResponse(access_token=create_access_token(employee.id, employee.token_version))


@router.post("/logout", status_code=204)
async def logout(
    user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    user.token_version += 1  # 이 계정의 기존 access·refresh 토큰 전부 무효화(§M2)
    await db.commit()
    # 이미 붙어 있는 사내톡 소켓도 끊는다 — 접속 시점만 검사하면 만료(30분)까지 살아남는다
    await manager.kick([user.id])
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
@limiter.limit("10/minute")  # verify 와 같은 값 — 한 흐름의 마지막 단계다
async def password_reset_confirm(
    request: Request, payload: PasswordResetConfirmReq, db: AsyncSession = Depends(get_db)
) -> None:
    employee_id = await consume_reset_token(payload.reset_token)
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(400, detail={"code": "INVALID_RESET_TOKEN", "message": "재설정 토큰이 유효하지 않습니다"})
    employee.password_hash = hash_password(payload.password)
    employee.token_version += 1  # 재설정 시 기존 세션 전부 무효화(§M2)
    await db.commit()
    await manager.kick([employee.id])  # 붙어 있는 소켓까지 끊는다
    return None
