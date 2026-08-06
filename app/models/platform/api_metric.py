"""API 응답 지표 — 분 단위 롤업 (모니터링 '성능' 탭).

요청 하나하나를 행으로 남기면 하루 수만 줄이라 감당이 안 된다. 그래서
**(분 · 메서드 · 주소)** 하나에 한 줄만 두고 거기에 누적한다. 미들웨어가
메모리에 모았다가 1분마다 `ON CONFLICT DO UPDATE` 로 더한다 — 워커가 여러
개여도 숫자가 안 어긋난다.

백분위(p50·p95·p99)는 **버킷 히스토그램**에서 보간해 낸다. 원본 시간을 다
들고 있어야 정확한 값이 나오는데 그게 바로 위에서 못 하기로 한 것이라,
Prometheus·Datadog 이 쓰는 것과 같은 방식으로 간다. 버킷 경계 사이는 선형
보간이라 오차가 있고, 경계를 촘촘히 둘수록 줄어든다. **낮은 쪽을 촘촘히 뒀다** —
요청 대부분이 수십 ms 안에 끝나서, 첫 칸이 굵으면 p50 이 그 칸 한가운데로
찍혀 실제보다 훨씬 크게 나온다 (0~50ms 한 칸이었을 때 평균 10ms 인데 p50 이 25 로 떴다).

보존기간은 접속 로그와 같다(access_log_retention_days, 기본 90일).
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin

# 응답 시간 버킷 경계(ms) — 이 값 **이하**가 그 칸에 들어간다.
# 마지막 칸은 경계를 넘긴 것 전부(`over`).
BUCKET_BOUNDS = (5, 10, 25, 50, 100, 250, 500, 1000, 3000)


class ApiMetric(UUIDMixin, Base):
    __tablename__ = "api_metrics"
    __table_args__ = (
        UniqueConstraint("minute", "method", "route", name="uq_api_metrics_slot"),
    )

    # 분 단위로 자른 시각 (초·마이크로초 0)
    minute: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)

    # id 를 {id} 로 바꾼 주소 — 활동 로그와 같은 정규화를 쓴다
    route: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 5xx — 서버가 터진 것. 4xx 와 갈라야 '에러율'이 뜻을 갖는다
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 4xx — 권한 없음·잘못된 입력 같은 것. 정상 동작일 수도 있다
    client_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 평균을 내려면 합이 필요하다. 밀리초 합이라 하루면 억 단위 → BigInteger
    sum_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    max_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 히스토그램 — 각 칸은 그 경계 이하로 끝난 요청 수
    b5: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    b10: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    b25: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    b50: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    b100: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    b250: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    b500: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    b1000: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    b3000: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    over: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
