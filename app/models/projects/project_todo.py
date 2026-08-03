"""ProjectTodo (프로젝트 체크리스트) 모델 — CLAUDE.md §6.1.

프로젝트의 할 일 항목. 완료 개수로 project.progress 를 서버가 자동 계산.
(독립 배정 태스크 Todo(§6.2)와는 별개 — 이건 프로젝트에 종속된 체크리스트.)
"""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class ProjectTodo(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "project_todos"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(String(300), nullable=False)
    assignee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 표시 순서
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
