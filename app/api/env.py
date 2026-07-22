"""환경정비 라우터 — EnvItem/EnvTaskLog/SupplyOrder (CLAUDE.md §4.2).

- 항목 정의: [ADMIN,MANAGER] / 수행(env-logs POST): [MEMBER]만 (§1 반복업무는 MEMBER 수행).
- 수행 → ENV 점수 적립, 취소(DELETE) → 연결 점수 회수.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.periods import period_range
from app.db.session import get_db
from app.enums import Role, ScoreCategory
from app.models.branch import Branch
from app.models.employee import Employee
from app.models.env import EnvItem, EnvTaskLog, SupplyOrder
from app.models.score_event import ScoreEvent
from app.schemas.env import (
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


# ---------- EnvItem (항목·배점) ----------
@router.get("/env-items", response_model=list[EnvItemOut], dependencies=[Depends(get_current_user)])
async def list_env_items(
    db: AsyncSession = Depends(get_db), branch_id: str | None = Query(None, alias="branchId")
) -> list[EnvItem]:
    stmt = select(EnvItem)
    if branch_id:
        stmt = stmt.where(EnvItem.branch_id == branch_id)
    result = await db.execute(stmt.order_by(EnvItem.points.desc(), EnvItem.name))
    return list(result.scalars().all())


@router.post("/env-items", response_model=EnvItemOut, status_code=201, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def create_env_item(payload: EnvItemCreate, db: AsyncSession = Depends(get_db)) -> EnvItem:
    if await db.get(Branch, payload.branch_id) is None:
        raise HTTPException(400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"})
    item = EnvItem(
        branch_id=payload.branch_id, name=payload.name, points=payload.points, editable=payload.editable
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
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


# ---------- EnvTaskLog (수행 기록 → 점수) ----------
@router.post("/env-logs", response_model=EnvTaskLogOut, status_code=201)
async def create_env_log(
    payload: EnvLogCreate,
    current: Employee = Depends(require_role(Role.MEMBER)),
    db: AsyncSession = Depends(get_db),
) -> EnvTaskLog:
    item = await db.get(EnvItem, payload.env_item_id)
    if item is None:
        raise HTTPException(400, detail={"code": "ENV_ITEM_NOT_FOUND", "message": "환경정비 항목이 존재하지 않습니다"})
    log = EnvTaskLog(
        employee_id=current.id,
        branch_id=item.branch_id,
        env_item_id=item.id,
        item_name=item.name,
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
        reason=item.name,
    )
    await db.commit()
    await db.refresh(log)
    return log


@router.get("/env-logs", response_model=list[EnvTaskLogOut], dependencies=[Depends(get_current_user)])
async def list_env_logs(
    db: AsyncSession = Depends(get_db),
    branch_id: str | None = Query(None, alias="branchId"),
    employee_id: str | None = Query(None, alias="employeeId"),
) -> list[EnvTaskLog]:
    stmt = select(EnvTaskLog)
    if branch_id:
        stmt = stmt.where(EnvTaskLog.branch_id == branch_id)
    if employee_id:
        stmt = stmt.where(EnvTaskLog.employee_id == employee_id)
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
    if current.role not in (Role.ADMIN, Role.MANAGER) and log.employee_id != current.id:
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
    branch_id: str | None = Query(None, alias="branchId"),
    month: str | None = Query(None),
) -> list[SupplyOrder]:
    stmt = select(SupplyOrder)
    if branch_id:
        stmt = stmt.where(SupplyOrder.branch_id == branch_id)
    if month:
        start, end = period_range(month)
        stmt = stmt.where(SupplyOrder.created_at >= start, SupplyOrder.created_at < end)
    result = await db.execute(stmt.order_by(SupplyOrder.created_at.desc()))
    return list(result.scalars().all())
