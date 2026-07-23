"""ContributionGrant (센터 기여도 지목 부여) 모델 — CLAUDE.md §4.4.

IDEA=5 / GOAL=10 / EXTRA_WORK=hours×3. SALES(매출성과)는 자동 계산이라 여기 저장 안 함.
"""

from sqlalchemy import Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import ContribType


class ContributionGrant(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "contribution_grants"

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    type: Mapped[ContribType] = mapped_column(
        SAEnum(ContribType, native_enum=False, length=20), nullable=False
    )
    hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # EXTRA_WORK 전용
    points: Mapped[int] = mapped_column(Integer, nullable=False)  # 서버 계산
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
