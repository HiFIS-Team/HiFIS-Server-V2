"""ProjectRequest (프로젝트 기한 변경 요청) 모델.

매니저·멤버가 프로젝트 기한 연장(EXTENSION) 또는 누락 사유(OVERDUE)를
새 기한 + 사유와 함께 제출 → 어드민이 승인(새 기한 반영)/반려(사유 필수).
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import ProjectRequestStatus, ProjectRequestType


class ProjectRequest(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "project_requests"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[ProjectRequestType] = mapped_column(
        SAEnum(ProjectRequestType, native_enum=False, length=20), nullable=False
    )
    new_due: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 제안 새 기한
    reason: Mapped[str] = mapped_column(Text, nullable=False)  # 연장/누락 사유
    status: Mapped[ProjectRequestStatus] = mapped_column(
        SAEnum(ProjectRequestStatus, native_enum=False, length=20),
        nullable=False,
        default=ProjectRequestStatus.PENDING,
    )
    requested_by_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id"), nullable=False, index=True
    )
    decided_by_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 반려 사유(필수)
