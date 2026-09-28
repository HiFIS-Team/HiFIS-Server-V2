"""이달의 목표 — MANAGER·MEMBER 가 달마다 스스로 적는다 (2026-09-28 대표 요청).

`매출 300만원 올리기` · `자격증 따기` 처럼 **글로 적는 목표 여러 줄**이다.
점수·결재와 무관하다 — 못 이뤄도 불이익이 없어서 승인 절차를 안 둔다.

**한 번 내면 그 달은 잠긴다.** 고칠 수 있으면 월말에 이룬 것만 남기게 된다.
사람·달당 한 줄이다.
"""

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class MonthlyGoal(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "monthly_goals"
    __table_args__ = (UniqueConstraint("employee_id", "year_month", name="uq_monthly_goal"),)

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    #: `YYYY-MM` (KST 달력 달)
    year_month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    #: 목표 한 줄씩 — 최소 2개
    items: Mapped[list] = mapped_column(JSON, nullable=False)
