"""Branch 라우터 — CLAUDE.md §2.1 (GET=로그인한 전원, POST/PATCH=[ADMIN]).

조회를 전원에게 연 이유: 사람·업무 데이터가 전부 branch_id 로만 오기 때문에
**지점 이름을 붙이려면 누구나 이 목록이 필요하다** (조직도 카드의 소속,
사내톡 상대 소속 등). 이름 자체는 약관에 공개된 값이라 가릴 것이 없다.
만들기·고치기는 그대로 ADMIN 전용이다.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import Role
from app.models.staff.branch import Branch
from app.schemas.staff.branch import BranchCreate, BranchOut, BranchUpdate

router = APIRouter(prefix="/branches", tags=["branches"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "BRANCH_NOT_FOUND", "message": "지점을 찾을 수 없습니다"})


@router.get("", response_model=list[BranchOut], dependencies=[Depends(get_current_user)])
async def list_branches(db: AsyncSession = Depends(get_db)) -> list[Branch]:
    result = await db.execute(select(Branch).order_by(Branch.created_at))
    return list(result.scalars().all())


@router.post("", response_model=BranchOut, status_code=201, dependencies=[Depends(require_role(Role.ADMIN))])
async def create_branch(payload: BranchCreate, db: AsyncSession = Depends(get_db)) -> Branch:
    branch = Branch(name=payload.name, type=payload.type)
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return branch


@router.get("/{branch_id}", response_model=BranchOut, dependencies=[Depends(get_current_user)])
async def get_branch(branch_id: str, db: AsyncSession = Depends(get_db)) -> Branch:
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise _not_found()
    return branch


@router.patch("/{branch_id}", response_model=BranchOut, dependencies=[Depends(require_role(Role.ADMIN))])
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
