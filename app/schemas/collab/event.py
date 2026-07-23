"""Event DTO — CLAUDE.md §6.8."""

from datetime import datetime

from app.schemas.base import CamelModel


class EventCreate(CamelModel):
    title: str
    start_at: datetime
    end_at: datetime
    category: str
    scope: str
    color: str
    memo: str | None = None


class EventUpdate(CamelModel):
    title: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    category: str | None = None
    scope: str | None = None
    color: str | None = None
    memo: str | None = None


class EventOut(CamelModel):
    id: str
    title: str
    start_at: datetime
    end_at: datetime
    category: str
    scope: str
    color: str
    memo: str | None = None
    owner_id: str
    created_at: datetime
