"""Auth DTO — CLAUDE.md §2.3."""

from app.schemas.base import CamelModel
from app.schemas.employee import EmployeeOut


class LoginRequest(CamelModel):
    email: str
    password: str


class TokenResponse(CamelModel):
    access_token: str
    refresh_token: str
    employee: EmployeeOut


class RefreshRequest(CamelModel):
    refresh_token: str


class AccessTokenResponse(CamelModel):
    access_token: str
