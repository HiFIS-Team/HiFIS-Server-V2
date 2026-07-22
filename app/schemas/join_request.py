"""JoinRequest DTO — CLAUDE.md §2.3.

approve body 는 문서에 없는 확장 — 승인 시 새 직원의 배치(지점·권한·직급)를 지정.
"""

from datetime import datetime

from app.enums import JoinRequestStatus, Rank, Role
from app.schemas.base import CamelModel


class JoinRequestOut(CamelModel):
    id: str
    name: str
    email: str
    status: JoinRequestStatus
    created_at: datetime


class JoinRequestApprove(CamelModel):
    branch_id: str
    role: Role = Role.MEMBER
    team: str | None = None
    rank: Rank | None = None
