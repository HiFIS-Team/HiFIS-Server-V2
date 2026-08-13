"""5xx 급증 감지 — 5분마다 `api_metrics` 를 훑는다 (모니터링 '성능').

**새로 재는 게 아니다.** 미들웨어가 이미 모든 요청을 분 단위로 모아 두고 있어서
(`ApiMetric.errors` = 5xx), 여기서는 그 값에 문턱만 건다.

배포 직후 뭐가 깨졌는지 제일 빨리 아는 길이다. 그라파나는 서버 바깥(디스크·CPU)을
보고, 이건 **앱 안**을 본다 — 마이그레이션이 반쯤 돌았거나 새 코드가 예외를
던지면 CPU 는 멀쩡한데 5xx 만 오른다.

## 왜 4xx 는 안 세나

`client_errors`(4xx)는 정상 동작일 수 있다 — 권한 없는 곳을 눌렀거나 입력이
틀린 것이다. 섞으면 문턱이 뜻을 잃는다.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models.chat.notification import Notification
from app.models.platform.api_metric import ApiMetric

logger = logging.getLogger(__name__)

# 얼마나 거슬러 보나 — 스캔 주기(5분)보다 길어야 사이에 낀 것을 안 놓친다
WINDOW_MIN = 10

# 이 비율(%)을 넘으면 알린다
ERROR_RATE_PCT = 5.0

# 요청이 이만큼은 있어야 비율을 따진다 — 2건 중 1건 실패를 50% 라고 부르면
# 새벽에 봇이 두 번 찔러도 알림이 간다
MIN_REQUESTS = 20

# 계속 걸려 있을 때 다시 알리기까지 — 그라파나 재알림(4시간)과 같은 값
RENOTIFY_HOURS = 4

_TYPE = "ERROR_RATE"


async def _recently_notified(db: AsyncSession, now: datetime) -> bool:
    """이미 알렸으면 조용히 넘어간다.

    스캔이 5분마다인데 사고는 몇 시간 갈 수 있다. 안 막으면 같은 사고로
    **5분마다 알림이 온다** — SSH 알림에서 겪은 것과 같은 종류다.

    상태를 따로 안 둔다. **알림 원장이 곧 "언제 알렸나"** 라서, 표를 새로
    만들면 같은 사실이 두 군데에 생긴다.
    """
    since = now - timedelta(hours=RENOTIFY_HOURS)
    hit = await db.scalar(
        select(Notification.id)
        .where(Notification.type == _TYPE, Notification.created_at >= since)
        .limit(1)
    )
    return hit is not None


async def error_rate_scan() -> None:
    from app.services.notifications import notify_developers

    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=WINDOW_MIN)

    async with SessionLocal() as db:
        total, errors = (
            await db.execute(
                select(
                    func.coalesce(func.sum(ApiMetric.count), 0),
                    func.coalesce(func.sum(ApiMetric.errors), 0),
                ).where(ApiMetric.minute >= since)
            )
        ).one()
        total, errors = int(total), int(errors)

        if total < MIN_REQUESTS or errors == 0:
            return
        rate = errors / total * 100
        if rate < ERROR_RATE_PCT:
            return
        if await _recently_notified(db, now):
            return

        # 어느 주소가 터지고 있나 — 이게 없으면 알림을 받고도 로그부터 뒤져야 한다
        worst = (
            await db.execute(
                select(ApiMetric.method, ApiMetric.route, func.sum(ApiMetric.errors).label("n"))
                .where(ApiMetric.minute >= since, ApiMetric.errors > 0)
                .group_by(ApiMetric.method, ApiMetric.route)
                .order_by(func.sum(ApiMetric.errors).desc())
                .limit(1)
            )
        ).first()
        where = f" · {worst[0]} {worst[1]}" if worst else ""

        logger.warning("5xx 급증: %.1f%% (%d/%d)%s", rate, errors, total, where)
        await notify_developers(
            db,
            type=_TYPE,
            title="서버 오류 급증",
            body=f"최근 {WINDOW_MIN}분 5xx {rate:.1f}% ({errors}/{total}){where}",
            link="/monitoring",
        )
        await db.commit()
