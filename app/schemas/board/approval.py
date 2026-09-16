"""Approval DTO — CLAUDE.md §6.5."""

from datetime import date, datetime

from app.enums import ApprovalStatus, ApprovalStepStatus
from app.schemas.base import CamelModel


class ApprovalStep(CamelModel):
    approver_id: str
    status: ApprovalStepStatus
    comment: str | None = None
    acted_at: datetime | None = None


class ApprovalComment(CamelModel):
    author_id: str
    body: str
    created_at: datetime


class ApprovalCreate(CamelModel):
    kind: str
    title: str
    content: str
    amount: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    place: str | None = None
    #: 순차 결재선 — **금액이 문턱 아래면 비워도 된다** (2026-09-16).
    #:
    #: 10만원 미만은 결재 없이 그대로 올라가므로 세울 사람이 없다.
    #: 서버가 `_needs_approval` 로 다시 보고, 받아야 하는데 비어 있으면
    #: `400 NEED_APPROVER` 로 막는다 — 앱이 안 실어 보내서 결재가 조용히
    #: 건너뛰어지는 일이 없어야 한다.
    approver_ids: list[str] = []


class ApprovalAction(CamelModel):
    comment: str | None = None


class CommentCreate(CamelModel):
    body: str


class ApprovalOut(CamelModel):
    id: str
    kind: str
    title: str
    content: str
    amount: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    place: str | None = None
    requester_id: str
    approver_ids: list[str]
    steps: list[ApprovalStep]
    status: ApprovalStatus
    current_approver_id: str | None = None
    comments: list[ApprovalComment]
    created_at: datetime
