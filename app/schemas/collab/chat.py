"""사내톡 DTO — CLAUDE.md §6.11."""

from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel
from app.schemas.collab.reaction import ReactionAgg


class ChatRoomCreate(CamelModel):
    member_ids: list[str] = Field(default_factory=list)  # 나 제외 상대(서버가 나 포함)
    name: str | None = None
    is_group: bool = False


class MessageCreate(CamelModel):
    body: str
    attachments: list[str] = Field(default_factory=list)


class MessageOut(CamelModel):
    id: str
    room_id: str
    sender_id: str
    body: str
    attachments: list[str] = Field(default_factory=list)
    reactions: list[ReactionAgg] = Field(default_factory=list)
    created_at: datetime


class ChatRoomOut(CamelModel):
    id: str
    name: str | None = None
    is_group: bool
    owner_id: str
    member_ids: list[str] = Field(default_factory=list)
    last_message: MessageOut | None = None
    unread_count: int = 0
    updated_at: datetime
