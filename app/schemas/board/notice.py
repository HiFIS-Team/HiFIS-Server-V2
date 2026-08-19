"""Notice DTO — CLAUDE.md §6.4."""

from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel
from app.schemas.board.reaction import ReactionAgg


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
    read_by_me: bool = False  # 내가 읽었는지
    read_count: int = 0       # 읽은 인원 수
    comment_count: int = 0    # 댓글 수 (2026-08-19) — 목록·상세의 말풍선 옆 숫자


class NoticeReaderItem(CamelModel):
    employee_id: str
    name: str
    avatar_color: str
    avatar_url: str | None = None
    read_at: datetime | None = None  # null = 아직 안 읽음


class NoticeReadersOut(CamelModel):
    """공지 확인 현황 — 대상 전원 + 읽음 여부(사람별 알약용)."""

    total: int          # 대상 인원(작성자 제외 재직 전원)
    read_count: int
    people: list[NoticeReaderItem]
