"""보존기간 파기 잡 (개인정보처리방침 §3, §7).

- 접속 로그·활동 로그: 통신비밀보호법상 3개월(access_log_retention_days) 초과분 삭제.
※ 향후 확장: 전자서명 이미지 등 다른 보존기간 파기도 여기에 추가.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.platform.access_log import AccessLog
from app.models.platform.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def purge_old_access_logs() -> None:
    """보존기간(기본 90일)이 지난 접속 로그·활동 로그를 파기한다.

    활동 로그(무엇을 바꿨는지)도 같은 기간을 쓴다 — 성격이 같은 기록이라
    한쪽만 오래 남길 이유가 없다.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.access_log_retention_days)
    async with SessionLocal() as db:
        access = await db.execute(delete(AccessLog).where(AccessLog.created_at < cutoff))
        audit = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        await db.commit()
        if access.rowcount or audit.rowcount:
            logger.info(
                "로그 파기: 접속 %d건 · 활동 %d건 (%s 이전)",
                access.rowcount,
                audit.rowcount,
                cutoff.date().isoformat(),
            )
