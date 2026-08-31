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


class PeerWindowOut(CamelModel):
    """지금 동료평가를 쓸 수 있나 — 앱의 안내 줄과 재촉 모달이 이걸 본다.

    **날짜 계산을 앱에 맡기지 않는다.** 대상 명단 규칙(같은 지점 현장 인원)이
    양쪽에 있으면 언젠가 갈리는데, 갈리면 화면에는 다 냈다고 나오고 서버는
    안 냈다고 깎는다.
    """

    #: 지금 창이 열려 있나 (말일·다음달 1일)
    is_open: bool
    #: 이 창이 평가하는 달 — 닫혀 있으면 None
    period: str | None = None
    #: 내가 평가해야 할 사람 수 (대표·관리자는 0)
    total: int = 0
    #: 그중 아직 안 낸 수 — 0 이면 다 낸 것이다
    remaining: int = 0
