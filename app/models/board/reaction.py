"""이모지 반응 모델 — 공지·회의록·채팅 공통 (CLAUDE.md §6.12).

저장은 (target, emoji, employee) 개별 행 1건씩. 출력은 서비스에서
{ emoji, employeeIds } 집계 형태로 변환 (app/services/reactions.py).
"""

from sqlalchemy import Enum as SAEnum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import ReactionTargetType


class Reaction(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "reactions"
    __table_args__ = (
        # 같은 대상에 같은 이모지를 한 사람이 한 번만 (토글 단위)
        UniqueConstraint("target_type", "target_id", "emoji", "employee_id", name="uq_reaction"),
    )

    target_type: Mapped[ReactionTargetType] = mapped_column(
        SAEnum(ReactionTargetType, native_enum=False, length=20), nullable=False, index=True
    )
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    emoji: Mapped[str] = mapped_column(String(32), nullable=False)
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
