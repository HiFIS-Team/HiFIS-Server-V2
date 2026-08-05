"""HourlyWagePolicy (시급) 모델 — 알바(EmploymentType.PART_TIME) 급여의 근거.

**시급을 코드에 박지 않는다.** 최저임금이 해마다 바뀌는데 상수로 두면
값을 올리는 순간 **지난 달 급여까지 새 시급으로 다시 계산된다.**
`effective_from` 으로 기간을 나눠 두면 그 달에 유효했던 시급이 그대로 쓰인다
(RankPolicy 와 같은 방식이다).

`branch_id` 가 null 이면 전사 기본, 지정하면 그 지점이 우선한다.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class HourlyWagePolicy(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "hourly_wage_policies"

    # 원 단위 (2026년 최저임금 10,320)
    wage: Mapped[int] = mapped_column(Integer, nullable=False)

    branch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=True
    )

    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
