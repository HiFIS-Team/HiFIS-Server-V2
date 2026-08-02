"""Todo DTO — CLAUDE.md §6.2."""

from datetime import datetime

from app.schemas.base import CamelModel


class TodoCreate(CamelModel):
    title: str
    due_at: datetime
    assignee_id: str


class TodoUpdate(CamelModel):
    title: str | None = None
    due_at: datetime | None = None
    done: bool | None = None


class TodoOut(CamelModel):
    id: str
    title: str
    due_at: datetime
    assignee_id: str
    assigned_by_id: str
    done: bool
    created_at: datetime
