"""Notice DTO — CLAUDE.md §6.4."""

from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel
from app.schemas.reaction import ReactionAgg


class NoticeCreate(CamelModel):
    title: str
    body: str
    pinned: bool = False


class NoticeUpdate(CamelModel):
    title: str | None = None
    body: str | None = None
    pinned: bool | None = None


class NoticeOut(CamelModel):
    id: str
    title: str
    body: str
    pinned: bool
    author_id: str
    created_at: datetime
    reactions: list[ReactionAgg] = Field(default_factory=list)  # §6.12 이모지 반응 집계
