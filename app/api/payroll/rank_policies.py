"""RankPolicy 라우터 — 직급별 급여·요율표 (CLAUDE.md §1, [ADMIN])."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import Rank, Role
from app.models.org.branch import Branch
from app.models.payroll.rank_policy import RankPolicy
from app.schemas.payroll.rank_policy import RankPolicyCreate, RankPolicyOut

router = APIRouter(prefix="/rank-policies", tags=["rank-policies"])


@router.get("", response_model=list[RankPolicyOut], dependencies=[Depends(get_current_user)])
async def list_rank_policies(
    db: AsyncSession = Depends(get_db),
    rank: Rank | None = Query(None),
    branch_id: str | None = Query(None, alias="branchId"),
) -> list[RankPolicy]:
    stmt = select(RankPolicy)
    if rank:
        stmt = stmt.where(RankPolicy.rank == rank)
    if branch_id:
        stmt = stmt.where(RankPolicy.branch_id == branch_id)
    result = await db.execute(stmt.order_by(RankPolicy.effective_from.desc()))
    return list(result.scalars().all())


@router.post("", response_model=RankPolicyOut, status_code=201, dependencies=[Depends(require_role(Role.ADMIN))])
async def create_rank_policy(payload: RankPolicyCreate, db: AsyncSession = Depends(get_db)) -> RankPolicy:
    if payload.branch_id is not None and await db.get(Branch, payload.branch_id) is None:
        raise HTTPException(400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"})
    policy = RankPolicy(
        rank=payload.rank,
        base_salary=payload.base_salary,
        new_rate=payload.new_rate,
        renewal_rate=payload.renewal_rate,
        branch_id=payload.branch_id,
        effective_from=payload.effective_from,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return policy


@router.delete("/{policy_id}", status_code=204, dependencies=[Depends(require_role(Role.ADMIN))])
async def delete_rank_policy(policy_id: str, db: AsyncSession = Depends(get_db)) -> None:
    policy = await db.get(RankPolicy, policy_id)
    if policy is None:
        raise HTTPException(404, detail={"code": "RANK_POLICY_NOT_FOUND", "message": "요율 정책을 찾을 수 없습니다"})
    await db.delete(policy)
    await db.commit()
    return None
