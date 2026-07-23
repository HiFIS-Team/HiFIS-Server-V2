"""계정 관리 DTO — CLAUDE.md §6.7. 응답에 비밀번호(평문) 절대 미포함."""

from typing import Literal

from app.schemas.base import CamelModel

AccountScope = Literal["전사", "팀", "프로젝트"]


class AccountCreate(CamelModel):
    name: str
    cat: str
    scope: AccountScope
    login_id: str
    password: str  # 입력 전용 — 암호화 저장, 응답 미포함
    url: str | None = None
    memo: str | None = None
    active: bool = True


class AccountUpdate(CamelModel):
    name: str | None = None
    cat: str | None = None
    scope: AccountScope | None = None
    login_id: str | None = None
    password: str | None = None  # 주면 재암호화
    url: str | None = None
    memo: str | None = None
    active: bool | None = None


class AccountOut(CamelModel):
    id: str
    name: str
    cat: str
    scope: AccountScope
    login_id: str
    url: str | None = None
    owner_id: str
    memo: str | None = None
    active: bool


class AccountSecretOut(CamelModel):
    password: str  # 복호화된 비번 — /secret 에서만
