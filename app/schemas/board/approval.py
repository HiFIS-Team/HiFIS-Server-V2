"""Approval DTO — CLAUDE.md §6.5."""

from datetime import date, datetime

from pydantic import Field

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
    approver_ids: list[str] = Field(min_length=1)  # 순차 결재선


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
