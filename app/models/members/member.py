"""Member (회원/고객) 모델 — CLAUDE.md §3.1."""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
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
    #: 운동을 하는 이유 — 문장 여러 줄. 상담에서 받아 적고 수업마다 다시 본다
    #:
    #: 줄마다 행을 두지 않는다. 순서가 곧 뜻이라 늘 통째로 읽고 통째로 쓴다.
    goals: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    #: 회원이 자기 수업을 보는 공개 주소의 마지막 칸 — `hifis.app/training/{token}`
    #:
    #: **회원 id 를 안 쓴다.** 새면 갈아 끼울 수 있어야 하고, id 가 새면 다른
    #: API 의 공격 재료가 된다. 설문 토큰(8자)보다 길게 잡는다 — 한 사람의
    #: 운동 기록 전부가 보이는 주소다.
    training_token: Mapped[str | None] = mapped_column(
        String(24), nullable=True, unique=True, index=True
    )
