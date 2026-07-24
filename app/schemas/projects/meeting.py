"""Meeting DTO — CLAUDE.md §6.3."""

from datetime import datetime

from pydantic import Field

from app.enums import MeetingScope
from app.schemas.base import CamelModel
from app.schemas.board.reaction import ReactionAgg


class MeetingCreate(CamelModel):
    title: str
    blocks: list = Field(default_factory=list)
    scope: MeetingScope
    attendee_ids: list[str] = Field(default_factory=list)
    project_id: str | None = None
    meeting_at: datetime


class MeetingUpdate(CamelModel):
    title: str | None = None
    blocks: list | None = None
    scope: MeetingScope | None = None
    attendee_ids: list[str] | None = None
    project_id: str | None = None
    meeting_at: datetime | None = None


class MeetingOut(CamelModel):
    id: str
    title: str
    blocks: list
    scope: MeetingScope
    attendee_ids: list[str]
    project_id: str | None = None
    author_id: str
    meeting_at: datetime
    created_at: datetime
    reactions: list[ReactionAgg] = Field(default_factory=list)  # §6.12 이모지 반응 집계
