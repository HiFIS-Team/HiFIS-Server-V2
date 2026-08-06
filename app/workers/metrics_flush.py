"""응답 시간 버퍼 내려쓰기 — 1분마다 (모니터링 '성능').

[app.core.metrics_middleware] 가 메모리에 모아 둔 것을 한 번에 DB 로 옮긴다.
같은 칸이 이미 있으면 **더한다** — 워커가 여럿이어도, 잡이 늦게 돌아
한 분에 두 번 내려써도 숫자가 안 어긋난다.

**리더 락 안에서 돌면 안 된다** — 버퍼는 워커마다 따로 쌓이므로
한 워커만 내려쓰면 나머지 워커가 받은 요청이 통째로 사라진다.
"""

import logging

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.core.metrics_middleware import take_buffer
from app.db.session import SessionLocal
from app.models.platform.api_metric import ApiMetric

logger = logging.getLogger(__name__)

# 더하는 칸 — 최대값(max_ms)만 규칙이 달라 따로 둔다
_SUMS = (
    "count",
    "errors",
    "client_errors",
    "sum_ms",
    "b5",
    "b10",
    "b25",
    "b50",
    "b100",
    "b250",
    "b500",
    "b1000",
    "b3000",
    "over",
)


async def flush_metrics() -> None:
    taken = take_buffer()
    if not taken:
        return

    async with SessionLocal() as db:
        for (minute, method, route), cell in taken.items():
            stmt = insert(ApiMetric).values(
                minute=minute, method=method, route=route, **cell
            )
            await db.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_api_metrics_slot",
                    set_={
                        **{
                            key: getattr(ApiMetric, key) + stmt.excluded[key]
                            for key in _SUMS
                        },
                        "max_ms": func.greatest(ApiMetric.max_ms, stmt.excluded.max_ms),
                    },
                )
            )
        await db.commit()
    logger.debug("응답 지표 %d칸 기록", len(taken))
