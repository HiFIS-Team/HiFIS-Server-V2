"""InviteKey (초대키) 모델 — CLAUDE.md §2.3."""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import InviteStatus, Rank, Role


class InviteKey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "invite_keys"

    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    branch_id: Mapped[str] = mapped_column(String(36), ForeignKey("branches.id"), nullable=False)
    role: Mapped[Role] = mapped_column(SAEnum(Role, native_enum=False, length=20), nullable=False)
    rank: Mapped[Rank] = mapped_column(SAEnum(Rank, native_enum=False, length=20), nullable=False)
    team: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[InviteStatus] = mapped_column(
        SAEnum(InviteStatus, native_enum=False, length=20),
        nullable=False,
        default=InviteStatus.UNUSED,
    )
    issued_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
