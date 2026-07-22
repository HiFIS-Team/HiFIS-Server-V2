"""PeerReview (동료평가) 모델 — CLAUDE.md §4.3.

별점 5항목(1~5). total 은 서버 계산(상대 평균×4 / 자기 평균×1). 제출 후 잠김 —
(reviewer, reviewee, period) 유니크. reviewee 가 받는 total 이 PEER 점수로 적립.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class PeerReview(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "peer_reviews"
    __table_args__ = (
        UniqueConstraint("reviewer_id", "reviewee_id", "period", name="uq_peer_review"),
    )

    reviewer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    reviewee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    is_self: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)

    competency: Mapped[int] = mapped_column(Integer, nullable=False)
    collaboration: Mapped[int] = mapped_column(Integer, nullable=False)
    contribution: Mapped[int] = mapped_column(Integer, nullable=False)
    attitude: Mapped[int] = mapped_column(Integer, nullable=False)
    leadership: Mapped[int] = mapped_column(Integer, nullable=False)

    reasons: Mapped[dict] = mapped_column(JSON, nullable=False)  # 항목별 사유
    total: Mapped[int] = mapped_column(Integer, nullable=False)  # 서버 계산
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
