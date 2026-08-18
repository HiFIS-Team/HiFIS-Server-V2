"""앱 사용 기록 — 앱이 올리고(전 직원) 대표가 본다(MASTER 전용).

무엇을 왜 남기는지는 `app/models/platform/app_trail.py` 에 적어 두었다.

| | 누가 | 무엇 |
|---|---|---|
| `POST /trails` | **전 직원** (앱이 자동으로) | 묶어서 올린다 |
| `GET /trails` | **MASTER 만** | 되짚어 본다 |

`POST` 에 권한 게이트가 없는 것은 `POST /security/capture` 와 같은 사정이다 —
앱이 알려 오는 자리라 게이트를 걸면 신고가 막힌다.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import Role
from app.models.platform.app_trail import AppTrail
from app.models.staff.employee import Employee
from app.schemas.platform.app_trail import TrailBatch, TrailOut

router = APIRouter(prefix="/trails", tags=["trails"])


@router.post("", status_code=204)
async def collect_trails(
    body: TrailBatch,
    request: Request,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """앱이 쌓아 둔 것을 묶어서 올린다 — **한 번에 여러 줄.**

    **활동 로그에는 안 남긴다** (`services/audit.py` 의 `SKIP`). 여기 담기는
    내용이 그대로 활동 로그에도 들어가면 같은 것이 두 벌로 쌓이는데, 이 표가
    셋 중 제일 양이 많은 자리라 그러면 감당이 안 된다.

    **대표는 안 남긴다.** 화면 캡처 방지와 같은 기준이다 — 대표는 지켜보는
    쪽이지 기록되는 쪽이 아니다. 앱도 안 보내지만 여기서도 막아 둔다
    (앱을 옛 빌드로 쓰는 기기가 있을 수 있다).
    """
    if current.role == Role.MASTER or not body.items:
        return Response(status_code=204)

    ip = request.client.host if request.client else None
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            AppTrail(
                employee_id=current.id,
                kind=item.kind,
                screen=item.screen,
                target=item.target,
                target_id=item.target_id,
                # 앱 시계가 틀어져 있어도 **미래로는 안 적는다** — 되짚을 때
                # 아직 오지 않은 시각의 줄이 맨 위에 서면 순서가 무너진다
                at=min(item.at, now),
                ip=ip,
            )
            for item in body.items
        ]
    )
    await db.commit()
    return Response(status_code=204)


@router.get("", response_model=list[TrailOut], dependencies=[Depends(require_role(Role.MASTER))])
async def list_trails(
    response: Response,
    employee_id: str | None = Query(None, alias="employeeId"),
    kind: str | None = Query(None, pattern="^(SCREEN|VIEW)$"),
    screen: str | None = Query(None, description="화면 이름으로 거르기"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    before: datetime | None = Query(
        None, description="이 시각까지만 — 장을 넘기는 동안 기준선을 고정한다"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[TrailOut]:
    """되짚어 보기 — 최신순, 번호 페이지. 총 건수는 `X-Total-Count` 로 준다.

    **`at`(앱에서 일어난 시각) 으로 세운다.** 서버 도착 시각으로 세우면 묶어
    보낸 것들이 한 덩어리로 뭉쳐서 실제 순서가 안 보인다.
    """
    where = []
    if employee_id:
        where.append(AppTrail.employee_id == employee_id)
    if kind:
        where.append(AppTrail.kind == kind)
    if screen:
        where.append(AppTrail.screen == screen)
    if before:
        where.append(AppTrail.at <= before)

    total = await db.scalar(select(func.count()).select_from(AppTrail).where(*where)) or 0
    response.headers["X-Total-Count"] = str(total)

    rows = list(
        await db.scalars(
            select(AppTrail)
            .where(*where)
            .order_by(AppTrail.at.desc(), AppTrail.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    # 이름을 붙인다 — 사람 수만큼만 조회한다 (줄마다 부르면 100줄에 100번이다)
    ids = {r.employee_id for r in rows if r.employee_id}
    names: dict[str, str] = {}
    if ids:
        names = {
            eid: name
            for eid, name in (
                await db.execute(select(Employee.id, Employee.name).where(Employee.id.in_(ids)))
            ).all()
        }
    out = []
    for row in rows:
        item = TrailOut.model_validate(row, from_attributes=True)
        item.employee_name = names.get(row.employee_id or "")
        out.append(item)
    return out
