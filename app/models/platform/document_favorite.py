"""DocumentFavorite (문서 즐겨찾기) 모델 — CLAUDE.md §6.6.

(문서·직원)당 최대 1행. 존재하면 '즐겨찾기', 없으면 아님. 공지 읽음(NoticeRead)과 같은 형태.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class DocumentFavorite(UUIDMixin, Base):
    __tablename__ = "document_favorites"
    __table_args__ = (UniqueConstraint("document_id", "employee_id", name="uq_document_favorite"),)

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False, index=True
    )
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
