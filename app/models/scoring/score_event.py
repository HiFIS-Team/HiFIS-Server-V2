"""ScoreEvent (점수 원장) 모델 — CLAUDE.md §4.1.

모든 카테고리 점수를 이 원장 하나로 적립(랭킹·진급 합산). points 음수=취소/감점.
"""

from sqlalchemy import Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import ScoreCategory


class ScoreEvent(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "score_events"

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=False, index=True
    )
    category: Mapped[ScoreCategory] = mapped_column(
        SAEnum(ScoreCategory, native_enum=False, length=20), nullable=False
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ref_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # 원천 기록 id
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # "2026-07"
    # 시스템 발생 점수(웹훅·스케줄러)는 부여 주체가 없어 null 허용
    created_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
