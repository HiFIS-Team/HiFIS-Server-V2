"""SQLAlchemy 선언적 베이스 + 공통 컬럼 mixin (CLAUDE.md §0, §8).

- ID: uuid 문자열
- 모든 엔티티: created_at / updated_at
- 소프트 삭제가 필요한 엔티티만 SoftDeleteMixin 추가 (deleted_at null=살아있음)
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_str() -> str:
    return str(uuid.uuid4())


class UUIDMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
