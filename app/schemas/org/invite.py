"""InviteKey DTO — CLAUDE.md §2.3."""

from datetime import datetime

from app.enums import InviteStatus, Rank, Role
from app.schemas.base import CamelModel


class InviteKeyCreate(CamelModel):
    branch_id: str
    role: Role
    rank: Rank  # 채용 직급 — 초대 시점에 확정
    team: str | None = None
    code: str | None = None  # 없으면 서버가 자동 생성
    expires_at: datetime | None = None  # 없으면 기본 14일


class InviteKeyOut(CamelModel):
    id: str
    code: str
    branch_id: str
    role: Role
    rank: Rank
    team: str | None = None
    status: InviteStatus
    issued_by_id: str
    expires_at: datetime
    created_at: datetime
