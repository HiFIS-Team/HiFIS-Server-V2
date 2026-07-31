"""Auth DTO — CLAUDE.md §2.3."""

import re
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.base import CamelModel
from app.schemas.staff.employee import EmployeeOut


def _normalize_phone(v: str) -> str:
    """휴대폰 번호 — 숫자만 남겨 10~11자리 검증(프론트 auth_signup.dart 와 동일 규칙)."""
    digits = re.sub(r"\D", "", v or "")
    if len(digits) not in (10, 11):
        raise ValueError("전화번호는 숫자 10~11자리여야 합니다")
    return digits


class LoginRequest(CamelModel):
    email: str
    password: str  # 로그인은 길이 검증 안 함(기존 계정 그대로 인증)


class SignupRequest(CamelModel):
    name: str
    email: str
    password: str = Field(min_length=8)  # 비밀번호 정책 — 최소 8자
    phone: str  # 필수 — 휴대폰 번호(정규화 저장)
    invite_key: str | None = None

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        return _normalize_phone(v)


class SignupResponse(CamelModel):
    result: Literal["JOINED", "PENDING"]


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
    password: str = Field(min_length=8)
