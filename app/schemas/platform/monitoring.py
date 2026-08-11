"""성능 지표·이상행동 DTO — 모니터링 화면 (개인정보처리방침 §8)."""

from datetime import datetime

from pydantic import Field

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


class CaptureReport(CamelModel):
    """앱이 '화면이 캡처됐다'고 알려 오는 것 — 본문은 활동 로그에 그대로 남는다.

    막을 수 있는 플랫폼(안드로이드·macOS·윈도우)에서는 애초에 캡처가 안 되므로
    **실제로는 iOS 만 보낸다.** 애플이 스크린샷을 막는 API 를 안 준다.
    """

    # ios · android · macos · windows — 어디서 왔는지
    platform: str = Field(max_length=20)

    # 무엇이 찍혔나 (`급여`·`조직도` 같은 화면 이름). 모르면 비운다
    screen: str | None = Field(default=None, max_length=60)

    # screenshot(찍힘) · recording(녹화·미러링 시작)
    kind: str = Field(default="screenshot", max_length=20)


class SshLoginReport(CamelModel):
    """서버에 **SSH 로 누가 들어왔다**고 서버 자신이 알려 오는 것.

    사람이 부르는 자리가 아니라 서버의 PAM 훅이 부른다 —
    그래서 로그인 토큰이 아니라 `X-Internal-Token` 헤더로 확인한다.

    2026-08-11 침해 사고 이후에 붙였다. 그때는 새벽에 들어온 것을
    **아무도 몰랐다** — 알림이 있었으면 그날 아침에 잡았을 자리다.
    """

    # 어느 계정으로 들어왔나 (`fitnessstar` 등)
    user: str = Field(max_length=64)

    # 어디서 들어왔나 — 접속 IP
    ip: str = Field(max_length=64)

    # open(접속) · close(종료). 지금은 open 만 보낸다
    event: str = Field(default="open", max_length=16)
