"""Branch DTO — CLAUDE.md §2.1."""

from datetime import datetime
from typing import Literal

from app.schemas.base import CamelModel

BranchType = Literal["HQ", "BRANCH"]


class BranchCreate(CamelModel):
    name: str
    type: BranchType = "BRANCH"


class BranchUpdate(CamelModel):
    name: str | None = None
    type: BranchType | None = None
    #: 회원에게 문자 보낼 때 쓰는 발신번호 — 빈 문자열을 주면 지운다
    #: (null 은 '안 건드림'이라 구분이 필요하다 — 문서함 이동과 같은 규칙)
    sms_sender: str | None = None


class BranchOut(CamelModel):
    id: str
    name: str
    type: BranchType
    #: 회원 문자 발신번호 — **비어 있으면 그 지점은 문자를 안 보낸다**
    sms_sender: str | None = None
    created_at: datetime
