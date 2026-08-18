"""보존기간 파기 잡 (개인정보처리방침 §3, §7).

- 접속 로그·활동 로그·응답 지표·이상행동: 3개월(access_log_retention_days) 초과분 삭제.
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
from app.models.platform.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def purge_old_access_logs() -> None:
    """보존기간(기본 90일)이 지난 접속·활동·앱 사용 기록·응답 지표·이상행동을 파기한다.

    다섯 다 같은 기간을 쓴다 — 성격이 같은 기록이라 한쪽만 오래 남길 이유가 없다.
    응답 지표는 개인정보가 아니지만 안 지우면 분 단위 행이 끝없이 쌓인다.

    **앱 사용 기록이 제일 빨리 는다** (화면을 옮길 때마다 한 줄). 안 지우면
    다른 넷을 합친 것보다 커진다.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.access_log_retention_days)
    async with SessionLocal() as db:
        access = await db.execute(delete(AccessLog).where(AccessLog.created_at < cutoff))
        audit = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        metric = await db.execute(delete(ApiMetric).where(ApiMetric.minute < cutoff))
        anomaly = await db.execute(delete(Anomaly).where(Anomaly.created_at < cutoff))
        trail = await db.execute(delete(AppTrail).where(AppTrail.created_at < cutoff))
        await db.commit()
        if (
            access.rowcount
            or audit.rowcount
            or metric.rowcount
            or anomaly.rowcount
            or trail.rowcount
        ):
            logger.info(
                "로그 파기: 접속 %d건 · 활동 %d건 · 지표 %d칸 · 이상행동 %d건 · 앱 사용 %d건 (%s 이전)",
                access.rowcount,
                audit.rowcount,
                metric.rowcount,
                anomaly.rowcount,
                trail.rowcount,
                cutoff.date().isoformat(),
            )
