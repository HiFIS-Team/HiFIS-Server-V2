"""Project DTO — CLAUDE.md §6.1."""

from datetime import datetime

from pydantic import Field

from app.enums import ProjectStatus
from app.schemas.base import CamelModel


class ProjectCreate(CamelModel):
    title: str
    purpose: str = ""
    steps: str = ""
    due: datetime
    progress: int = Field(default=0, ge=0, le=100)
    assignee_ids: list[str] = Field(default_factory=list)


class ProjectUpdate(CamelModel):
    title: str | None = None
    purpose: str | None = None
    steps: str | None = None
    due: datetime | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    assignee_ids: list[str] | None = None
    extension_reason: str | None = None


class ProjectOut(CamelModel):
    id: str
    title: str
    purpose: str
    steps: str
    due: datetime
    progress: int
    assignee_ids: list[str]
    extension_reason: str | None = None
    status: ProjectStatus  # 서버 파생
    created_by_id: str
    created_at: datetime
