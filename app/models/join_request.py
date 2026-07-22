"""JoinRequest (가입 승인 대기) 모델 — CLAUDE.md §2.3.

password_hash 는 wire 에 없는 서버 전용 컬럼 — 승인 시 그대로 Employee 로 이관.
"""

from sqlalchemy import Enum as SAEnum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import JoinRequestStatus


class JoinRequest(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "join_requests"

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[JoinRequestStatus] = mapped_column(
        SAEnum(JoinRequestStatus, native_enum=False, length=20),
        nullable=False,
        default=JoinRequestStatus.PENDING,
    )
