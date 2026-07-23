"""알림·웹푸시 모델 — Notification · PushSubscription (CLAUDE.md §6.10, §9.4)."""

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Notification(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)  # APPROVAL/NOTICE/LEAVE ...
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 앱 내 딥링크
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)


class PushSubscription(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "push_subscriptions"

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)  # keys.p256dh
    auth: Mapped[str] = mapped_column(String(255), nullable=False)    # keys.auth
