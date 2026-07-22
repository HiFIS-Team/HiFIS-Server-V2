"""Member DTO — CLAUDE.md §3.1."""

from datetime import datetime

from app.schemas.base import CamelModel


class MemberCreate(CamelModel):
    name: str
    phone: str
    branch_id: str
    owner_trainer_id: str
    referrer_member_id: str | None = None
    memo: str | None = None


class MemberUpdate(CamelModel):
    name: str | None = None
    phone: str | None = None
    owner_trainer_id: str | None = None
    referrer_member_id: str | None = None
    memo: str | None = None


class MemberOut(CamelModel):
    id: str
    name: str
    phone: str
    branch_id: str
    owner_trainer_id: str
    referrer_member_id: str | None = None
    registered_at: datetime
    memo: str | None = None
