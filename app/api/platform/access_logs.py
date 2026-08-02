"""접속 로그 조회 — 관리자 이상 접근 모니터링 (개인정보처리방침 §8).

읽기 전용. `[ADMIN]` 게이트라 MASTER 도 자동 통과 — 승인·반려가 아니므로 ADMIN(조회 권한)도 열람 가능.
전 지점 보안 데이터이므로 지점 스코프는 적용하지 않는다.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.enums import AccessEvent, Role
from app.models.platform.access_log import AccessLog
from app.schemas.platform.access_log import AccessLogOut

router = APIRouter(prefix="/access-logs", tags=["access-logs"])


@router.get("", response_model=list[AccessLogOut], dependencies=[Depends(require_role(Role.ADMIN))])
async def list_access_logs(
    employee_id: str | None = Query(None, alias="employeeId"),
    event: AccessEvent | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[AccessLog]:
    stmt = select(AccessLog).order_by(AccessLog.created_at.desc()).limit(limit)
    if employee_id:
        stmt = stmt.where(AccessLog.employee_id == employee_id)
    if event is not None:
        stmt = stmt.where(AccessLog.event == event)
    return list((await db.scalars(stmt)).all())
