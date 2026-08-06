"""활동 로그 조회 — 누가 무엇을 바꿨는지 (개인정보처리방침 §8).

읽기 전용. **MASTER 전용** — 접속 로그·사내톡 열람과 같은 기준이다 (ADMIN 도 403).
전 지점 보안 데이터이므로 지점 스코프는 적용하지 않는다.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.enums import Role
from app.models.platform.audit_log import AuditLog
from app.schemas.platform.audit_log import AuditLogOut
from app.services.audit import READ_LOGGED

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])

# 열람 기록 — 관리자가 남의 기록·대화를 '들여다본' 줄.
# 한 일이 아니라 지켜본 일이라, 목록에서는 기본으로 빼고 따로 본다.
# (남기는 것 자체는 그대로다 — 개인정보처리방침 §8-1)
_READ_ROUTES = sorted({route for method, route in READ_LOGGED if method == "GET"})


def _is_read(stmt_col=AuditLog):
    return and_(stmt_col.method == "GET", stmt_col.route.in_(_READ_ROUTES))


@router.get("", response_model=list[AuditLogOut], dependencies=[Depends(require_role(Role.MASTER))])
async def list_audit_logs(
    response: Response,
    employee_id: str | None = Query(None, alias="employeeId"),
    route: str | None = Query(None, description="정규화된 주소 — 예: /notices/{id}"),
    failed_only: bool = Query(False, alias="failedOnly", description="막힌 시도만"),
    reads: str = Query(
        "exclude",
        pattern="^(exclude|only|include)$",
        description="열람 기록 처리 — exclude(기본) 빼기 · only 그것만 · include 섞기",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, description="번호 페이지 — limit 의 배수로 넘긴다"),
    before: datetime | None = Query(
        None, description="이 시각까지만 — 장을 넘기는 동안 기준선을 고정한다"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLog]:
    """번호 페이지로 준다. 몇 장인지는 응답 헤더로 알려 준다.

    `X-Total-Count`  열람 기록·막힌 시도를 빼고 센 건수 (탭 라벨 '활동 N')
    `X-Failed-Count` 그중 막힌 것 (탭 라벨 '막힌 시도 N')
    `X-Read-Count`   열람 기록 건수 (탭 라벨 '열람 N')

    페이지 수는 지금 보고 있는 탭에 걸린 쪽을 쓴다.

    **열람 기록은 기본으로 빠진다.** 관리자가 이 화면을 열 때마다 '활동 기록
    열람' 이 한 줄씩 쌓여서, 안 빼면 목록 맨 위가 본인 열람으로 채워진다
    (실제로 413건 중 102건이 그랬다). 기록은 그대로 남는다 — 화면에서만 가른다.

    **`before` 를 같이 보내야 장이 안 밀린다.** 이 조회 자체가 활동 로그로
    남기 때문에(READ_LOGGED) 장을 넘길 때마다 앞에 새 줄이 끼어들어, 기준선을
    안 고정하면 같은 줄이 두 장에 걸쳐 나온다 (실제로 장마다 1건씩 겹쳤다).
    """

    def narrowed(stmt):  # 실패 여부를 뺀 공통 조건 — 두 세기와 목록이 같이 쓴다
        if employee_id:
            stmt = stmt.where(AuditLog.employee_id == employee_id)
        if before is not None:
            stmt = stmt.where(AuditLog.created_at <= before)
        if route:
            stmt = stmt.where(AuditLog.route == route)
        return stmt

    work = narrowed(select(func.count()).select_from(AuditLog)).where(~_is_read())
    total = await db.scalar(work)
    failed = await db.scalar(work.where(AuditLog.status >= 400))
    read = await db.scalar(
        narrowed(select(func.count()).select_from(AuditLog)).where(_is_read())
    )
    response.headers["X-Total-Count"] = str(total or 0)
    response.headers["X-Failed-Count"] = str(failed or 0)
    response.headers["X-Read-Count"] = str(read or 0)

    stmt = narrowed(select(AuditLog))
    if reads == "exclude":
        stmt = stmt.where(~_is_read())
    elif reads == "only":
        stmt = stmt.where(_is_read())
    if failed_only:
        stmt = stmt.where(AuditLog.status >= 400)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    return list((await db.scalars(stmt)).all())
