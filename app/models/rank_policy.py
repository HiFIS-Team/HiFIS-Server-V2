"""RankPolicy (직급별 급여·요율) 모델 — CLAUDE.md §1.

요율/기본급 하드코딩 금지 → 이 테이블로. branch_id 지정 시 해당 지점 우선, null=전사 기본.
effective_from 으로 기간별 변경 대비.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import Rank


class RankPolicy(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "rank_policies"

    rank: Mapped[Rank] = mapped_column(SAEnum(Rank, native_enum=False, length=20), nullable=False, index=True)
    base_salary: Mapped[int] = mapped_column(Integer, nullable=False)
    new_rate: Mapped[float] = mapped_column(Float, nullable=False)       # 신규 PT 인센 (예 0.4)
    renewal_rate: Mapped[float] = mapped_column(Float, nullable=False)   # 재등록 인센 (예 0.5)
    branch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=True
    )
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
