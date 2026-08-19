"""글 댓글 스키마 — 공지·회의록 공통 (2026-08-19)."""

from datetime import datetime

from pydantic import Field

from app.enums import CommentTargetType
from app.schemas.base import CamelModel


class CommentCreate(CamelModel):
    target_type: CommentTargetType
    target_id: str
    body: str = Field(min_length=1, max_length=2000)


class CommentUpdate(CamelModel):
    body: str = Field(min_length=1, max_length=2000)


class CommentOut(CamelModel):
    id: str
    target_type: CommentTargetType
    target_id: str
    author_id: str
    body: str
    created_at: datetime
    updated_at: datetime
