"""RankingSnapshot — 순위 변동 감지용 마지막 순위 스냅샷 (CLAUDE.md §4.1 랭킹).

(kind, period, employee_id) 당 1행. 5분 스캔 잡이 현재 순위와 비교해 '누가 나를 앞질렀나'를
감지하고 새 순위로 갱신한다. 랭킹 자체는 ScoreEvent 합산으로 계산 — 이 표는 diff 기준선일 뿐.
"""

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class RankingSnapshot(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ranking_snapshots"
    __table_args__ = (
        UniqueConstraint("kind", "period", "employee_id", name="uq_ranking_snapshot"),
    )

    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # RankingKind
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # "2026-07"
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)     # 1 = 1등
    points: Mapped[int] = mapped_column(Integer, nullable=False)
