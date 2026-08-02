"""PeerReview DTO — CLAUDE.md §4.3."""

from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel


class PeerScores(CamelModel):
    competency: int = Field(ge=1, le=5)
    collaboration: int = Field(ge=1, le=5)
    contribution: int = Field(ge=1, le=5)
    attitude: int = Field(ge=1, le=5)
    leadership: int = Field(ge=1, le=5)


class PeerReviewCreate(CamelModel):
    reviewee_id: str
    period: str
    scores: PeerScores
    reasons: dict[str, str]  # 항목별 사유 (필수)


class PeerReviewOut(CamelModel):
    id: str
    reviewer_id: str
    reviewee_id: str
    is_self: bool
    period: str
    scores: PeerScores
    reasons: dict[str, str]
    total: int
    submitted_at: datetime


class PeerAggregateItem(CamelModel):
    reviewee_id: str
    name: str
    review_count: int
    total: int
    by_category: dict[str, int]
