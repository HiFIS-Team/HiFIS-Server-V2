"""Branch 라우터 — CLAUDE.md §2.1.

TODO(auth): 인증(Phase 1) 붙이면 GET=[ADMIN,MANAGER], POST/PATCH=[ADMIN] 가드 추가.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.branch import Branch
from app.schemas.branch import BranchCreate, BranchOut, BranchUpdate

router = APIRouter(prefix="/branches", tags=["branches"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "BRANCH_NOT_FOUND", "message": "지점을 찾을 수 없습니다"})


@router.get("", response_model=list[BranchOut])
async def list_branches(db: AsyncSession = Depends(get_db)) -> list[Branch]:
    result = await db.execute(select(Branch).order_by(Branch.created_at))
    return list(result.scalars().all())


@router.post("", response_model=BranchOut, status_code=201)
async def create_branch(payload: BranchCreate, db: AsyncSession = Depends(get_db)) -> Branch:
    branch = Branch(name=payload.name, type=payload.type)
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return branch


@router.get("/{branch_id}", response_model=BranchOut)
async def get_branch(branch_id: str, db: AsyncSession = Depends(get_db)) -> Branch:
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise _not_found()
    return branch


@router.patch("/{branch_id}", response_model=BranchOut)
async def update_branch(
    branch_id: str, payload: BranchUpdate, db: AsyncSession = Depends(get_db)
) -> Branch:
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise _not_found()
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(branch, key, value)
    await db.commit()
    await db.refresh(branch)
    return branch
