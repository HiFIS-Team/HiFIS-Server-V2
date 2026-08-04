"""활동 로그 조회 — 누가 무엇을 바꿨는지 (개인정보처리방침 §8).

읽기 전용. `[ADMIN]` 게이트라 MASTER 도 자동 통과 — 접속 로그와 같은 기준이다.
전 지점 보안 데이터이므로 지점 스코프는 적용하지 않는다.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.enums import Role
from app.models.platform.audit_log import AuditLog
from app.schemas.platform.audit_log import AuditLogOut

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=list[AuditLogOut], dependencies=[Depends(require_role(Role.ADMIN))])
async def list_audit_logs(
    employee_id: str | None = Query(None, alias="employeeId"),
    route: str | None = Query(None, description="정규화된 주소 — 예: /notices/{id}"),
    failed_only: bool = Query(False, alias="failedOnly", description="막힌 시도만"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if employee_id:
        stmt = stmt.where(AuditLog.employee_id == employee_id)
    if route:
        stmt = stmt.where(AuditLog.route == route)
    if failed_only:
        stmt = stmt.where(AuditLog.status >= 400)
    return list((await db.scalars(stmt)).all())
