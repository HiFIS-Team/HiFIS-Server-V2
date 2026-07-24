"""Approval (전자결재) 모델 — CLAUDE.md §6.5.

순차 결재선: approver_ids 순서대로. current_approver_id 가 지금 처리할 차례.
steps/comments 는 JSONB(표시용). 한 명이라도 반려하면 전체 REJECTED.
"""

from datetime import date

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import ApprovalStatus


class Approval(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "approvals"

    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    place: Mapped[str | None] = mapped_column(String(200), nullable=True)

    requester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    approver_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # 순차 결재선
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus, native_enum=False, length=20),
        nullable=False,
        default=ApprovalStatus.IN_PROGRESS,
    )
    current_approver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True, index=True
    )
    comments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
