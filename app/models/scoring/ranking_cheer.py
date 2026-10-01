"""지난달 랭킹 1위 축하 — 누가 누구에게 그달 보냈나 (2026-09-30 대표 요청).

랭킹이 굳은 뒤 첫 접속에 축하 페이지가 뜨고, 1위 줄의 이모지를 누르면 그 사람에게
푸시가 간다. **한 사람이 한 1위에게 그달 한 번만** — 여러 분야 1위여도 한 번이다
(분야마다 울리면 세 분야 1위는 같은 사람에게 세 번 받는다).
"""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class RankingCheer(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ranking_cheers"
    __table_args__ = (UniqueConstraint("from_id", "to_id", "period", name="uq_ranking_cheer"),)

    from_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), nullable=False)
    to_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    #: 축하하는 랭킹의 달 `YYYY-MM`
    period: Mapped[str] = mapped_column(String(7), nullable=False)
