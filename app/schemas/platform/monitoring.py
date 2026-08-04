"""성능 지표·이상행동 DTO — 모니터링 화면 (개인정보처리방침 §8)."""

from datetime import datetime

from app.enums import AnomalyKind
from app.schemas.base import CamelModel


class SlowRouteOut(CamelModel):
    """느린 주소 한 줄 — 어디를 손봐야 하는지"""

    method: str
    route: str
    count: int
    avg_ms: int
    p95_ms: int
    max_ms: int
    errors: int


class ApiMetricsOut(CamelModel):
    """지정한 기간의 응답 지표 한 장.

    백분위는 버킷 히스토그램에서 보간한 값이라 **근사치**다 (원본을 다 들고
    있어야 정확한데 그러면 하루 수만 줄이 쌓인다 — Prometheus 와 같은 방식).
    """

    minutes: int  # 본 기간 (분)
    requests: int
    rpm: float  # 분당 요청 수
    error_rate: float  # 5xx 비율 (%)
    client_error_rate: float  # 4xx 비율 (%)
    avg_ms: int
    p50_ms: int
    p95_ms: int
    p99_ms: int
    max_ms: int
    slowest: list[SlowRouteOut]

    # 분마다 요청 수·평균 — 화면의 꺾은선
    timeline: list["MetricPointOut"]


class MetricPointOut(CamelModel):
    minute: datetime
    count: int
    avg_ms: int
    errors: int


class AnomalyOut(CamelModel):
    id: str
    kind: AnomalyKind
    employee_id: str | None = None
    subject: str
    detail: str
    count: int
    ip: str | None = None
    user_agent: str | None = None
    resolved_at: datetime | None = None
    resolved_by_id: str | None = None
    created_at: datetime
