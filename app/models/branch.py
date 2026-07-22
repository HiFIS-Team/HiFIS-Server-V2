"""Branch (지점) 모델 — CLAUDE.md §2.1."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Branch(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "branches"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="BRANCH")  # HQ | BRANCH
