"""환경정비 라우터 — EnvItem/EnvTaskLog/SupplyOrder (CLAUDE.md §4.2).

- 항목 정의: [ADMIN,MANAGER] / 수행(env-logs POST): [MEMBER,MANAGER] (점장도 정비 수행. ADMIN·MASTER 제외).
- 수행 → ENV 점수 적립, 취소(DELETE) → 연결 점수 회수.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_pick, branch_scope, get_current_user, require_role
from app.core.periods import KST, period_range
from app.db.session import get_db
from app.enums import Role, ScoreCategory
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.models.scoring.env import EnvItem, EnvTaskLog, SupplyOrder
from app.models.scoring.score_event import ScoreEvent
from app.schemas.scoring.env import (
    EnvItemCreate,
    EnvItemOut,
    EnvItemUpdate,
    EnvLogCreate,
    EnvTaskLogOut,
    SupplyOrderCreate,
    SupplyOrderOut,
)
from app.services.scoring import accrue_score

router = APIRouter(tags=["env"])


# 기본 환경정비 항목 (최종 점수표). 지점마다 없으면 자동 생성 —
# (이름, 배점, editable). editable=False 는 고정 보호(수정/삭제 불가).
# '기타'는 1~10 범위라 editable=True 로 두어 지점별 조정 가능(항목을 바꾸려면 이 상수를 고칠 것).
# 순서 = 하루 일하는 흐름(§31): 빨래 → 청소 → 관리 → 홍보 → 기타.
# (배점순 아님 — 현수막이 청소 사이에 끼거나 화장실청소가 홍보 뒤로 가지 않도록)
#
# **이 차례는 앱이 정한다.** 칩을 위에서 아래로 훑으며 누르게 돼 있어서
# 실제 일하는 차례와 다르면 손이 왔다 갔다 한다. 임의로 바꾸지 않는다.
BASE_ENV_ITEMS: list[tuple[str, int, bool]] = [
    # 빨래 — 돌리고, 말리고, 갠다. 이 차례가 뒤집히면 안 된다
    ("세탁", 1, False),
    ("건조기", 1, False),
    ("빨래정리", 2, False),   # 3 → 2 (2026-08-13 대표 결정)
    # 청소 — 넓은 곳부터 탈의실, 화장실 순
    ("구역청소", 2, False),
    ("복도청소", 2, False),
    ("락커정리", 2, False),
    ("남탈부스", 5, False),
    ("남탈청소", 2, False),
    ("여탈부스", 5, False),
    ("여탈청소", 2, False),
    ("화장실청소", 2, False),  # 5 → 2 (2026-08-13 대표 결정)
    # 관리
    ("기구관리", 2, False),
    ("회원지도", 2, False),
    ("TM회원관리", 1, False),
    # 홍보 — 온라인부터 오프라인
    ("게시물", 3, False),
    ("스토리", 3, False),
    ("전단지", 10, False),
    ("현수막", 10, False),
    ("족자", 5, False),
    ("블로그", 10, False),
    # 기타 — 어쩌다 하는 것들
    ("클레임해결", 10, False),
    ("기타", 1, True),  # 1~10 범위 → 지점별 조정 가능
]


async def _ensure_base_items(db: AsyncSession, branch_id: str) -> None:
    """지점에 환경정비 항목이 하나도 없으면 기본 항목을 심는다 (멱등).

    DB 초기화/부분 삭제 후에도 첫 조회 때 자동 복구 → 수동 재시드 불필요.
    """
    existing = await db.execute(select(EnvItem.id).where(EnvItem.branch_id == branch_id).limit(1))
    if existing.first() is not None:
        return
    if await db.get(Branch, branch_id) is None:  # 실재하는 지점만
        return
    for i, (name, points, editable) in enumerate(BASE_ENV_ITEMS):
        db.add(EnvItem(branch_id=branch_id, name=name, points=points, editable=editable, sort_order=i))
    await db.commit()


# ---------- EnvItem (항목·배점) ----------
@router.get("/env-items", response_model=list[EnvItemOut], dependencies=[Depends(get_current_user)])
async def list_env_items(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_pick),
) -> list[EnvItem]:
    # 기본 항목 자동 보충: 특정 지점이 대상이면 그 지점, 아니면(ADMIN 전체 조회) 모든 지점
    if scope:
        await _ensure_base_items(db, scope)
    else:
        for (bid,) in (await db.execute(select(Branch.id))).all():
            await _ensure_base_items(db, bid)

    stmt = select(EnvItem)
    if scope:
        stmt = stmt.where(EnvItem.branch_id == scope)
    result = await db.execute(stmt.order_by(EnvItem.sort_order, EnvItem.name))  # 고정 순서(§4.2 #31)
    return list(result.scalars().all())


@router.post("/env-items", response_model=EnvItemOut, status_code=201, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def create_env_item(payload: EnvItemCreate, db: AsyncSession = Depends(get_db)) -> EnvItem:
    if await db.get(Branch, payload.branch_id) is None:
        raise HTTPException(400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"})
    item = EnvItem(
        branch_id=payload.branch_id, name=payload.name, points=payload.points,
        editable=payload.editable, sort_order=payload.sort_order,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/env-items/{item_id}", response_model=EnvItemOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def update_env_item(
    item_id: str, payload: EnvItemUpdate, db: AsyncSession = Depends(get_db)
) -> EnvItem:
    item = await db.get(EnvItem, item_id)
    if item is None:
        raise HTTPException(404, detail={"code": "ENV_ITEM_NOT_FOUND", "message": "환경정비 항목을 찾을 수 없습니다"})
    if not item.editable:  # 기본 고정 항목은 수정 불가 (삭제는 엔드포인트 자체가 없음)
        raise HTTPException(403, detail={"code": "ENV_ITEM_LOCKED", "message": "기본 항목은 수정할 수 없습니다"})
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


# ---------- EnvTaskLog (수행 기록 → 점수) ----------
@router.post("/env-logs", response_model=EnvTaskLogOut, status_code=201)
async def create_env_log(
    payload: EnvLogCreate,
    # 점장(MANAGER)도 정비를 수행함 → 허용. ADMIN·MASTER 는 운영 전담이라 제외(세션 싸인과 동일).
    current: Employee = Depends(require_role(Role.MEMBER, Role.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> EnvTaskLog:
    item = await db.get(EnvItem, payload.env_item_id)
    if item is None:
        raise HTTPException(400, detail={"code": "ENV_ITEM_NOT_FOUND", "message": "환경정비 항목이 존재하지 않습니다"})
    # 남의 지점 항목은 수행으로 안 받는다. MANAGER 가 헤더 고르개로 다른 지점을
    # 볼 수 있게 되면서(`branch_pick`) 생긴 자리다 — 그 지점 칩을 누르면
    # `branch_id=item.branch_id` 라 **남의 지점에 내 점수가 쌓인다.**
    # 보는 것만 열고 하는 것은 본인 지점에 둔다.
    if item.branch_id != current.branch_id:
        raise HTTPException(403, detail={"code": "OTHER_BRANCH", "message": "다른 지점의 항목은 수행할 수 없습니다"})
    # 기타 등 write-in: 적은 내용을 라벨에 접어 "기타(창고정리)" 로 스냅샷(점수 원장·랭킹 사유도 동일). item_name String(100) 보호.
    label = f"{item.name}({payload.note})"[:100] if payload.note else item.name
    log = EnvTaskLog(
        employee_id=current.id,
        branch_id=item.branch_id,
        env_item_id=item.id,
        item_name=label,
        points=item.points,
        note=payload.note,
    )
    db.add(log)
    await db.flush()
    await accrue_score(
        db,
        employee_id=current.id,
        branch_id=item.branch_id,
        category=ScoreCategory.ENV,
        points=item.points,
        created_by_id=current.id,
        source_ref_id=log.id,
        reason=label,
    )
    await db.commit()
    await db.refresh(log)
    return log


@router.get("/env-logs", response_model=list[EnvTaskLogOut], dependencies=[Depends(get_current_user)])
async def list_env_logs(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_pick),
    employee_id: str | None = Query(None, alias="employeeId"),
    date: str | None = Query(None),      # "YYYY-MM-DD" — 하루치(KST). 앱 '오늘' 필터
    period: str | None = Query(None),    # "YYYY-MM" — 월치(세션 싸인과 동일)
) -> list[EnvTaskLog]:
    stmt = select(EnvTaskLog)
    if scope:
        stmt = stmt.where(EnvTaskLog.branch_id == scope)
    if employee_id:
        stmt = stmt.where(EnvTaskLog.employee_id == employee_id)
    if date:
        try:
            d = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, detail={"code": "INVALID_DATE", "message": "date 형식은 YYYY-MM-DD 입니다"})
        day_start = datetime(d.year, d.month, d.day, tzinfo=KST)  # KST 하루 → created_at(UTC) 비교
        stmt = stmt.where(EnvTaskLog.created_at >= day_start, EnvTaskLog.created_at < day_start + timedelta(days=1))
    if period:
        start, end = period_range(period)
        stmt = stmt.where(EnvTaskLog.created_at >= start, EnvTaskLog.created_at < end)
    result = await db.execute(stmt.order_by(EnvTaskLog.created_at.desc()))
    return list(result.scalars().all())


@router.delete("/env-logs/{log_id}", status_code=204)
async def delete_env_log(
    log_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    log = await db.get(EnvTaskLog, log_id)
    if log is None:
        raise HTTPException(404, detail={"code": "ENV_LOG_NOT_FOUND", "message": "수행 기록을 찾을 수 없습니다"})
    if current.role not in (Role.MASTER, Role.ADMIN, Role.MANAGER) and log.employee_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 기록만 취소할 수 있습니다"})
    # 연결된 ENV 점수 회수 (− 취소)
    await db.execute(
        delete(ScoreEvent).where(
            ScoreEvent.source_ref_id == log.id, ScoreEvent.category == ScoreCategory.ENV
        )
    )
    await db.delete(log)
    await db.commit()
    return None


# ---------- SupplyOrder (비품) ----------
@router.post("/supply-orders", response_model=SupplyOrderOut, status_code=201)
async def create_supply_order(
    payload: SupplyOrderCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupplyOrder:
    if await db.get(Branch, payload.branch_id) is None:
        raise HTTPException(400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"})
    order = SupplyOrder(
        branch_id=payload.branch_id,
        item_name=payload.item_name,
        price=payload.price,
        ordered_by_id=current.id,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


@router.get("/supply-orders", response_model=list[SupplyOrderOut], dependencies=[Depends(get_current_user)])
async def list_supply_orders(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    branch_id: str | None = Query(None, alias="branchId"),
    month: str | None = Query(None),
) -> list[SupplyOrder]:
    stmt = select(SupplyOrder)
    if scope:
        stmt = stmt.where(SupplyOrder.branch_id == scope)
    if branch_id:
        stmt = stmt.where(SupplyOrder.branch_id == branch_id)
    if month:
        start, end = period_range(month)
        stmt = stmt.where(SupplyOrder.created_at >= start, SupplyOrder.created_at < end)
    result = await db.execute(stmt.order_by(SupplyOrder.created_at.desc()))
    return list(result.scalars().all())
