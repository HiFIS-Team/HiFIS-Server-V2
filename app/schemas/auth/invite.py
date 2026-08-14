"""InviteKey DTO — CLAUDE.md §2.3."""

from datetime import datetime

from app.enums import EmploymentType, InviteStatus, Rank, Role
from app.schemas.base import CamelModel


class InviteKeyCreate(CamelModel):
    branch_id: str
    role: Role
    rank: Rank  # 채용 직급 — 초대 시점에 확정
    #: 고용 형태 — 안 주면 정규직. 알바로 뽑을 때만 실어 보낸다.
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    team: str | None = None
    #: **코드는 요청자가 못 정한다 — 서버가 만든다** (2026-08-14).
    #:
    #: 예전에는 `code` 를 받아 그대로 썼다. 사람이 `hifis2026` 같은 걸 넣으면
    #: 자동 생성값의 43억 가지가 한순간에 무너진다. 앱은 원래 안 보내고 있었고
    #: (`InviteKeyApi.create` 가 지점·권한·직군·고용형태만 싣는다) 서버에서도
    #: 쓰던 데가 자동 생성 폴백 한 줄뿐이라 칸 자체를 없앴다.
    expires_at: datetime | None = None  # 없으면 기본 14일


class InviteKeyOut(CamelModel):
    id: str
    code: str
    branch_id: str
    role: Role
    rank: Rank
    employment_type: EmploymentType
    team: str | None = None
    status: InviteStatus
    issued_by_id: str
    expires_at: datetime
    created_at: datetime
