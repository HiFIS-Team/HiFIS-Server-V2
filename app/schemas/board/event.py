"""Event DTO — CLAUDE.md §6.8."""

from datetime import datetime

from pydantic import Field

from app.enums import EventStatus
from app.schemas.base import CamelModel


class EventCreate(CamelModel):
    title: str
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    category: str
    scope: str
    color: str
    place: str | None = None
    attendee_ids: list[str] = Field(default_factory=list)
    memo: str | None = None


class EventUpdate(CamelModel):
    title: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day: bool | None = None
    category: str | None = None
    scope: str | None = None
    color: str | None = None
    place: str | None = None
    attendee_ids: list[str] | None = None
    memo: str | None = None


class EventOut(CamelModel):
    id: str
    title: str
    start_at: datetime
    end_at: datetime
    all_day: bool
    category: str
    scope: str
    color: str
    place: str | None = None
    attendee_ids: list[str]
    memo: str | None = None
    owner_id: str
    status: EventStatus  # 요청자가 못 정한다 — 올린 사람의 권한이 정한다
    created_at: datetime
    updated_at: datetime
