"""응답 시간 계측 — 모든 요청을 재서 분 단위로 모은다 (모니터링 '성능').

요청마다 DB 에 한 줄씩 쓰면 **요청 수만큼 쓰기가 배로 는다.** 그래서 여기서는
메모리에만 더하고, 1분마다 도는 잡([app.workers.metrics_flush])이 한 번에
내려 쓴다. 워커가 여러 개여도 `ON CONFLICT DO UPDATE` 로 더하기라 안 어긋난다.

활동 로그(`AuditMiddleware`)와 나란히 걸리지만 성격이 다르다 —
저쪽은 '누가 무엇을 바꿨나'라 쓰기만 보고, 이쪽은 **전부** 본다.
"""

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.models.platform.api_metric import BUCKET_BOUNDS
from app.services.audit import normalize

logger = logging.getLogger(__name__)

_BUCKET_KEYS = tuple(f"b{bound}" for bound in BUCKET_BOUNDS)

# 칸 이름은 **경계에서 만들어 낸다.** 손으로 적어 두면 경계를 바꿨을 때
# 여기만 옛 이름이 남는다 (실제로 그래서 모든 요청이 500 이 났다).
_EMPTY = {
    "count": 0,
    "errors": 0,
    "client_errors": 0,
    "sum_ms": 0,
    "max_ms": 0,
    "over": 0,
    **{key: 0 for key in _BUCKET_KEYS},
}

# (분, 메서드, 주소) → 누적값. 잡이 비우기 전까지 여기 쌓인다.
_BUFFER: dict[tuple[datetime, str, str], dict[str, int]] = defaultdict(_EMPTY.copy)

# 재지 않는 것 — 지표를 보러 온 요청이 지표를 흔들면 안 된다
_SKIP_PREFIXES = ("/metrics", "/docs", "/openapi", "/redoc", "/health", "/files")


def take_buffer() -> dict[tuple[datetime, str, str], dict[str, int]]:
    """모아 둔 것을 통째로 넘기고 버퍼를 비운다 — 잡이 부른다.

    비우는 사이에 들어온 요청은 새 버퍼에 쌓이므로 한 건도 안 샌다.
    """
    global _BUFFER
    taken, _BUFFER = _BUFFER, defaultdict(_EMPTY.copy)
    return taken


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(_SKIP_PREFIXES):
            return await call_next(request)

        started = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            # 터진 요청도 지표에는 남아야 한다 — 에러율이 그걸로 뜬다
            self._safe_record(request, 500, time.perf_counter() - started)
            raise
        self._safe_record(request, status, time.perf_counter() - started)
        return response

    def _safe_record(self, request: Request, status: int, seconds: float) -> None:
        """계측이 요청을 죽이면 안 된다 — 재는 쪽 잘못으로 500 이 나간 적이 있다"""
        try:
            self._record(request, status, seconds)
        except Exception:
            logger.exception("응답 지표 기록 실패: %s %s", request.method, request.url.path)

    def _record(self, request: Request, status: int, seconds: float) -> None:
        now = datetime.now(timezone.utc)
        slot = (now.replace(second=0, microsecond=0), request.method, normalize(request.url.path)[:200])
        ms = int(seconds * 1000)

        cell = _BUFFER[slot]
        cell["count"] += 1
        cell["sum_ms"] += ms
        cell["max_ms"] = max(cell["max_ms"], ms)
        if status >= 500:
            cell["errors"] += 1
        elif status >= 400:
            cell["client_errors"] += 1

        for bound, key in zip(BUCKET_BOUNDS, _BUCKET_KEYS):
            if ms <= bound:
                cell[key] += 1
                break
        else:
            cell["over"] += 1
