"""ProjectActivity (프로젝트 상세 타임라인) 모델 — CLAUDE.md §6.1.

한 테이블에 댓글(kind=COMMENT)과 시스템 활동 기록(진행률·기한·완료 등)을 함께 쌓아
'상세 타임라인' 하나로 보여준다. 시스템 활동은 actor_id 가 실행자(없으면 null).
"""

from sqlalchemy import Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import ProjectActivityKind


class ProjectActivity(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "project_activities"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False, index=True
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True  # null=시스템
    )
    kind: Mapped[ProjectActivityKind] = mapped_column(
        SAEnum(ProjectActivityKind, native_enum=False, length=20), nullable=False
    )
    body: Mapped[str | None] = mapped_column(Text, nullable=True)  # 댓글 본문 / 활동 메시지
