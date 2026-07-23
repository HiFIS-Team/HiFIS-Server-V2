"""Auth DTO — CLAUDE.md §2.3."""

from typing import Literal

from app.schemas.base import CamelModel
from app.schemas.org.employee import EmployeeOut


class LoginRequest(CamelModel):
    email: str
    password: str


class SignupRequest(CamelModel):
    name: str
    email: str
    password: str
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
