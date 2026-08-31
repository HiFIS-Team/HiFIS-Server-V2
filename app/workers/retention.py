"""보존기간 파기 잡 (개인정보처리방침 §3, §7).

- 접속 로그·활동 로그·앱 사용 기록·응답 지표·이상행동·**알림함**:
  3개월(`access_log_retention_days`) 초과분 삭제.

## 여기 안 넣는 것 — 지우면 안 되는 것들

| 테이블 | 하루 | 왜 안 지우나 |
|---|---|---|
| `score_events` | 144행 | **점수 원장이다.** 랭킹·기여도·급여 근거가 여기서 나온다 |
| `env_task_logs` | 123행 | 환경정비 점수의 근거 — 위와 같은 이유 |

둘 다 계속 자란다(각각 1년에 5만 행쯤). **그건 인덱스로 푸는 문제지 지워서
푸는 문제가 아니다.** 지우면 지난 달 랭킹을 다시 못 뽑는다.

※ 향후 확장: 전자서명 이미지 등 다른 보존기간 파기도 여기에 추가.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.platform.access_log import AccessLog
from app.models.platform.anomaly import Anomaly
from app.models.platform.app_trail import AppTrail
from app.models.platform.api_metric import ApiMetric
from app.models.chat.notification import Notification
from app.models.platform.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def purge_old_access_logs() -> None:
    """보존기간(기본 90일)이 지난 접속·활동·앱 사용 기록·응답 지표·이상행동·알림을 파기한다.

    여섯 다 같은 기간을 쓴다 — 성격이 같은 기록이라 한쪽만 오래 남길 이유가 없다.
    응답 지표는 개인정보가 아니지만 안 지우면 분 단위 행이 끝없이 쌓인다.

    **앱 사용 기록이 제일 빨리 는다** (화면을 옮길 때마다 한 줄). 안 지우면
    다른 넷을 합친 것보다 커진다.

    **알림함은 화면이 못 읽는 것만 지운다.** `GET /notifications` 가 `days` 를
    최대 90 까지만 받아서(`le=90`), 그보다 오래된 알림은 **어떤 경로로도 못
    꺼낸다** — 안 읽음 배지도 그 목록을 세므로 배지에도 안 잡힌다. 나머지
    읽는 자리(스캔 실패 중복 거르기 10분, 5xx 재알림 몇 시간)도 다 그 안쪽이다.
    그래서 지워도 **화면이 하나도 안 바뀐다.**
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.access_log_retention_days)
    async with SessionLocal() as db:
        access = await db.execute(delete(AccessLog).where(AccessLog.created_at < cutoff))
        audit = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        metric = await db.execute(delete(ApiMetric).where(ApiMetric.minute < cutoff))
        anomaly = await db.execute(delete(Anomaly).where(Anomaly.created_at < cutoff))
        trail = await db.execute(delete(AppTrail).where(AppTrail.created_at < cutoff))
        noti = await db.execute(delete(Notification).where(Notification.created_at < cutoff))
        await db.commit()
        if (
            access.rowcount
            or audit.rowcount
            or metric.rowcount
            or anomaly.rowcount
            or trail.rowcount
            or noti.rowcount
        ):
            logger.info(
                "로그 파기: 접속 %d건 · 활동 %d건 · 지표 %d칸 · 이상행동 %d건 · "
                "앱 사용 %d건 · 알림 %d건 (%s 이전)",
                access.rowcount,
                audit.rowcount,
                metric.rowcount,
                anomaly.rowcount,
                trail.rowcount,
                noti.rowcount,
                cutoff.date().isoformat(),
            )
