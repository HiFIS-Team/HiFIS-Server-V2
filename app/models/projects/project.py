"""Project (프로젝트) 모델 — CLAUDE.md §6.1.

status(대기/진행중/완료/누락)는 progress+due 파생 → 저장 안 함, 응답 시 계산.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    steps: Mapped[str] = mapped_column(Text, nullable=False, default="")
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 시작일(null=미설정, 앱은 createdAt 폴백)
    due: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 체크리스트 있으면 완료율 자동, 없으면 수동
    assignee_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # 맡은 사람 — 만든 사람과 다를 수 있다(대표가 만들어 트레이너에게 맡긴다).
    # null 이면 만든 사람이 담당이다(이 컬럼이 생기기 전에 올린 프로젝트).
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True, index=True
    )
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 사용자가 고른 색(null=앱이 id 해시로 생성)
    extension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 누락(마감 초과) 알림을 보낸 시각 — 1회만 보내기 위한 멱등 표시. 마감(due) 변경 시 초기화.
    overdue_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 완료 알림을 보낸 시각 — 위와 같은 이유의 멱등 표시.
    # 완료 정산(`_settle_completion`)은 진행률을 건드릴 때마다 불린다. 이 표시가
    # 없으면 **이미 100% 인 프로젝트를 고칠 때마다 '완료' 알림이 다시 나간다.**
    # 100% 아래로 내려가면 비운다 — 다시 완료하면 그때 또 알린다.
    completed_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )

    #: 어느 지점의 프로젝트인가 — **만들 때 만든 사람의 지점을 찍는다** (2026-08-19).
    #:
    #: 같은 `Branch.share_group` 끼리만 서로 본다. 만든 사람이 나중에 지점을
    #: 옮겨도 이 값은 안 따라간다 — 옮길 때마다 옛 프로젝트가 통째로 다른 지점으로
    #: 넘어가면 안 된다(그래서 조회할 때 사람 지점을 조인하지 않고 컬럼으로 뒀다).
    #:
    #: **`NULL` 은 전 지점**이다 — 본사(HQ)가 만든 것과 이 컬럼이 생기기 전 것.
    branch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=True, index=True
    )
