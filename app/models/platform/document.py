"""문서함 모델 — Folder · Document (CLAUDE.md §6.6)."""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Folder(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "folders"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    space: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("folders.id"), nullable=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )


class Document(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    ext: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)  # serving 경로 (다운로드는 별도 엔드포인트)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    space: Mapped[str] = mapped_column(String(50), nullable=False)
    folder_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("folders.id"), nullable=True, index=True
    )
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # 'desc' 는 SQL 예약어 → DB 컬럼명은 description, 파이썬/wire 는 desc
    desc: Mapped[str | None] = mapped_column("description", Text, nullable=True)
    uploader_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
