"""RankOvertake — 랭킹판에서 누가 누구를 앞질렀는지 (대표·관리자 랭킹 화면).

랭킹은 볼 때마다 원본에서 다시 계산하는 값이라 **지난 상태를 아무도 기억하지
않는다.** 5분 스캔 잡이 순위를 찍어 직전(`RankingSnapshot`)과 비교하고,
자리가 바뀐 것만 여기 한 줄로 남긴다.

`RankingSnapshot` 과 짝이다 — 저쪽은 '지금 어디쯤인가'(다음 비교의 기준선),
이쪽은 '언제 누가 누구를 넘었나'(지나간 사건). 기준선은 덮어써도 되지만
사건은 쌓여야 한다.

**항목 이름은 `ranking_board.METRICS` 를 따른다** (`revenue`·`kindness`·
`project`·`care`·`lesson`·`overall`). 점수 원장 기반의 `RankingKind` 와는
다른 축이다 — 앱 랭킹 화면이 보는 값이 이쪽이라 여기에 맞춘다.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class RankOvertake(UUIDMixin, Base):
    __tablename__ = "rank_overtakes"

    # "2026-08"
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)

    # ranking_board.METRICS 중 하나
    metric: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # 앞지른 사람
    mover_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    # 밀려난 사람
    passed_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    # 넘어선 순간의 값 차이 — 매출이면 원, 수업이면 개수다.
    # 항목마다 단위가 달라서 **화면이 항목을 보고 붙인다.**
    gap: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    # 앞지른 사람의 새 등수 (밀려난 사람은 여기서 한 칸 아래다)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
