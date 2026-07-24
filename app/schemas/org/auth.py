"""Auth DTO — CLAUDE.md §2.3."""

from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel
from app.schemas.org.employee import EmployeeOut


class LoginRequest(CamelModel):
    email: str
    password: str  # 로그인은 길이 검증 안 함(기존 계정 그대로 인증)


class SignupRequest(CamelModel):
    name: str
    email: str
    password: str = Field(min_length=8)  # 비밀번호 정책 — 최소 8자
    invite_key: str | None = None


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
