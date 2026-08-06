"""PaydayPolicy (지점×직급별 급여 지급일·주기) 모델.

지급일을 코드에 박아 두면 지점이 늘거나 규칙이 바뀔 때마다 배포해야 한다.
`RankPolicy`·`HourlyWagePolicy` 와 같은 방식으로 DB 에 둔다.

**지점만으로는 안 갈린다** — 같은 첨단 안에서도 FC 는 말일, 트레이너는 익월 10일이다.
그래서 `branch_id` 와 `rank` 를 둘 다 두고, 좁은 쪽이 이긴다:

    (지점+직급) > (지점) > (직급) > (전사 기본)
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import Rank


class PaydayPolicy(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "payday_policies"

    #: null = 전사 기본
    branch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=True, index=True
    )
    #: null = 그 지점의 모든 직급
    rank: Mapped[Rank | None] = mapped_column(
        SAEnum(Rank, native_enum=False, length=20), nullable=True, index=True
    )

    #: 지급일(1~28). **null 이면 말일** — 달마다 날짜가 달라서 숫자로 못 적는다.
    day: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: 익월 지급인가.
    #:
    #: - `False` (당월) — 주기 `[그달 1일, 다음달 1일)`, 지급 = 그 주기의 **말일**
    #: - `True`  (익월) — 주기 `[전월 day, 그달 day)`, 지급 = 그달 **day** 일
    #:
    #: 화순·FC 가 앞이고(말일), 동광주·첨단 트레이너가 뒤다(익월 10일).
    next_month: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: 이 규칙으로 **급여를 재기 시작하는 날**.
    #:
    #: 주기 시작이 이 날보다 이르면 명세서를 만들지 않는다 — 앱을 켜기 전의
    #: 실적까지 급여로 잡으면 안 준 돈이 생긴 것처럼 보인다.
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)

    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
