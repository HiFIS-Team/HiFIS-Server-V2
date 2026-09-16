"""RankingFreeze — **지난달 랭킹판을 통째로 굳혀 둔다** (2026-09-16 대표 요청)

[RankingSnapshot] 과 이름이 비슷하지만 **하는 일이 다르다.**

| | 무엇을 담나 | 왜 |
|---|---|---|
| `RankingSnapshot` | (종류·달·사람)당 **직전 순위 한 줄** | 5분 스캔이 '누가 나를 앞질렀나'를 재는 기준선 |
| `RankingFreeze` | (달·지점)당 **판 전체** | 끝난 달이 더는 안 움직이게 굳히는 것 |
"""

from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class RankingFreeze(UUIDMixin, TimestampMixin, Base):
    """한 달·한 지점의 랭킹판을 통째로 담아 둔 줄

    **왜 굳히나** — 랭킹은 매번 원본(등록권 결제액·점수 원장)에서 다시 셌다.
    그래서 **지난 데이터를 고치면 지난 랭킹이 같이 움직였다.** 실제로 9월에
    잘못 넣은 등록권을 0원으로 고쳤더니 그 달 매출 순위가 바뀌었다.
    전달 통계는 그 달로 끝나야 하는 값이라 1일 00:00 에 찍어 굳힌다.

    **판을 통째로 담는다** (`rows`). 항목이 여섯이고 앞으로 늘 수 있는데
    칸으로 쪼개 두면 항목이 늘 때마다 표를 고쳐야 한다 — 찍는 순간의 모양
    그대로 두는 것이 안전하다. 읽는 쪽은 `build_board` 가 주던 것과 같은
    모양을 그대로 받는다.
    """

    __tablename__ = "ranking_freezes"
    __table_args__ = (
        UniqueConstraint("period", "branch_id", name="uq_ranking_freeze_scope"),
    )

    #: `2026-08`
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    #: null 이면 **전 지점**. 지점을 고른 판은 따로 찍는다 — 지점별로 순위가
    #: 다시 매겨져서 전사 판에서 잘라 낼 수가 없다
    branch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    #: `build_board` 가 돌려주던 그 목록 그대로
    rows: Mapped[list] = mapped_column(JSON, nullable=False)
