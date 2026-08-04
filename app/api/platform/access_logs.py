"""접속 로그 조회 — 관리자 이상 접근 모니터링 (개인정보처리방침 §8).

읽기 전용. **MASTER 전용** — 남이 언제 어디서 접속했는지가 보이는 자리라 대표만 연다 (ADMIN 도 403).
전 지점 보안 데이터이므로 지점 스코프는 적용하지 않는다.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.enums import AccessEvent, Role
from app.models.platform.access_log import AccessLog
from app.schemas.platform.access_log import AccessLogOut

router = APIRouter(prefix="/access-logs", tags=["access-logs"])


@router.get("", response_model=list[AccessLogOut], dependencies=[Depends(require_role(Role.MASTER))])
async def list_access_logs(
    response: Response,
    employee_id: str | None = Query(None, alias="employeeId"),
    event: AccessEvent | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, description="번호 페이지 — limit 의 배수로 넘긴다"),
    before: datetime | None = Query(
        None, description="이 시각까지만 — 장을 넘기는 동안 기준선을 고정한다"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[AccessLog]:
    """번호 페이지로 준다. 몇 장인지는 응답 헤더로 알려 준다 (활동 로그와 같다).

    `X-Total-Count`  이벤트 종류를 빼고 센 전체 건수 (탭 라벨 '전체 N')
    `X-Failed-Count` 그중 로그인 실패 (탭 라벨 '실패 N')

    `before` 로 기준선을 고정한다 — 활동 로그와 같은 이유다.
    """

    def narrowed(stmt):  # 이벤트를 뺀 공통 조건 — 두 세기와 목록이 같이 쓴다
        if employee_id:
            stmt = stmt.where(AccessLog.employee_id == employee_id)
        if before is not None:
            stmt = stmt.where(AccessLog.created_at <= before)
        return stmt

    total = await db.scalar(narrowed(select(func.count()).select_from(AccessLog)))
    failed = await db.scalar(
        narrowed(select(func.count()).select_from(AccessLog)).where(
            AccessLog.event == AccessEvent.LOGIN_FAIL
        )
    )
    response.headers["X-Total-Count"] = str(total or 0)
    response.headers["X-Failed-Count"] = str(failed or 0)

    stmt = narrowed(select(AccessLog))
    if event is not None:
        stmt = stmt.where(AccessLog.event == event)
    stmt = stmt.order_by(AccessLog.created_at.desc()).limit(limit).offset(offset)
    return list((await db.scalars(stmt)).all())
