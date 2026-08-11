"""Member (회원/고객) 모델 — CLAUDE.md §3.1."""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import VisitPath


class Member(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "members"

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=False, index=True
    )
    # 담당 트레이너 — 매출 인센 귀속 (§3.1)
    owner_trainer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    referrer_member_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("members.id"), nullable=True
    )
    #: 어떻게 알고 왔나 — 등록할 때 받는다. 블로그·인스타·OT→PT 면 담당
    #: 트레이너에게 5점이 붙는다 (`VISIT_PATH_SCORE`).
    #:
    #: **nullable 이다.** 이 칸이 생기기 전에 등록된 회원과, 아직 업데이트를
    #: 안 받은 앱이 보내는 등록을 받아야 한다 (앱이 필수로 막는다).
    visit_path: Mapped[VisitPath | None] = mapped_column(
        SAEnum(VisitPath, native_enum=False, length=20), nullable=True
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
