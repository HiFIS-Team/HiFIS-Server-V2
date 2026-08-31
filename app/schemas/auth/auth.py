"""Auth DTO — CLAUDE.md §2.3."""

from typing import Literal

from pydantic import Field, field_validator

from app.schemas.base import CamelModel, normalize_phone
from app.schemas.staff.employee import EmployeeOut


class LoginRequest(CamelModel):
    email: str
    password: str  # 로그인은 길이 검증 안 함(기존 계정 그대로 인증)


class ConsentAgreement(CamelModel):
    """가입 화면에서 체크한 동의 한 건."""

    doc_type: str = Field(min_length=1, max_length=40)   # "TERMS" / "PRIVACY"
    doc_version: str = Field(min_length=1, max_length=40)


class SignupRequest(CamelModel):
    name: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)  # 비밀번호 정책 — 최소 8자
    phone: str = Field(max_length=30)  # 필수 — 휴대폰 번호(정규화 저장)
    invite_key: str = Field(min_length=1, max_length=64)  # 필수 — 회원가입은 초대키만(승인 대기 폐지)
    #: 약관·개인정보 동의 — **가입과 같은 트랜잭션에 남긴다.**
    #: 예전엔 앱이 가입 후 잠깐 로그인해 따로 불렀는데, 그사이 실패하면
    #: 동의 기록 없는 계정만 남았다(입증 책임은 회사에 있다).
    #:
    #: 비어 있어도 받는다 — 스토어에 이미 깔린 구버전 앱은 이 칸을 안 보낸다.
    #: 그쪽은 여전히 `POST /employees/me/consents` 로 따로 남긴다.
    #: **모든 기기가 올라가면 필수로 바꾼다.**
    consents: list[ConsentAgreement] = Field(default_factory=list)

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        return normalize_phone(v)


class SignupResponse(CamelModel):
    result: Literal["JOINED"]  # 승인 대기(PENDING) 폐지 — 유효 초대키만 가입


class TokenResponse(CamelModel):
    access_token: str
    refresh_token: str
    employee: EmployeeOut


class RefreshRequest(CamelModel):
    refresh_token: str


class AccessTokenResponse(CamelModel):
    access_token: str


# --- 비밀번호 재설정 (비로그인) — 3단계 (CLAUDE.md §2.3) ---
class PasswordResetRequestReq(CamelModel):
    method: Literal["EMAIL", "PHONE"]  # 발송 채널 선택(정규화는 contact 로 판별)
    contact: str                       # 이메일 또는 전화번호


class PasswordResetVerifyReq(CamelModel):
    contact: str
    code: str


class PasswordResetVerifyResp(CamelModel):
    reset_token: str  # confirm 단계에서 사용(단일 사용)


class PasswordResetConfirmReq(CamelModel):
    reset_token: str
    password: str = Field(min_length=8, max_length=128)
