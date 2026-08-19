"""글 댓글 모델 — 공지·회의록 공통 (2026-08-19).

반응([Reaction])과 **같은 다형 구조**다 — `target_type` + `target_id` 로
어느 글에 달렸는지만 가리킨다. 그래서 나중에 다른 글에 붙일 때도
테이블을 새로 만들 필요가 없다.

프로젝트 댓글(`project_activities`)과는 별개다. 저쪽은 **시스템 활동과 댓글이
한 타임라인**에 섞여 있어서(기한 변경·체크 완료가 같이 쌓인다) 여기에 못 얹는다.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import CommentTargetType


class Comment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "comments"

    target_type: Mapped[CommentTargetType] = mapped_column(
        SAEnum(CommentTargetType, native_enum=False, length=20), nullable=False, index=True
    )
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    #: 지운 시각 — **행을 지우지 않고 표시만 한다** (null 이면 살아 있다).
    #:
    #: 사내톡 전송 취소와 같은 이유다 — 나중에 답글이 붙으면 원문이 통째로
    #: 사라졌을 때 그 답글이 뜻을 잃는다. 지금은 답글이 없지만 구조를 맞춰 둔다.
    #: 조회에서는 빠지고, 개수에도 안 센다.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
