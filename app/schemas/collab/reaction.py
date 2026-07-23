"""이모지 반응 DTO — CLAUDE.md §6.12."""

from pydantic import Field

from app.enums import ReactionTargetType
from app.schemas.base import CamelModel


class ReactionToggle(CamelModel):
    target_type: ReactionTargetType
    target_id: str
    emoji: str


class ReactionAgg(CamelModel):
    """집계 형태 — 한 대상의 이모지별 누른 사람 목록."""

    emoji: str
    employee_ids: list[str] = Field(default_factory=list)


class ToggleResult(CamelModel):
    added: bool  # True=추가 / False=제거
    reactions: list[ReactionAgg] = Field(default_factory=list)  # 토글 후 최신 집계
