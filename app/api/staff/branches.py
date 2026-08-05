"""Branch 라우터 — CLAUDE.md §2.1 (GET=로그인한 전원, POST/PATCH=[ADMIN]).

조회를 전원에게 연 이유: 사람·업무 데이터가 전부 branch_id 로만 오기 때문에
**지점 이름을 붙이려면 누구나 이 목록이 필요하다** (조직도 카드의 소속,
사내톡 상대 소속 등). 이름 자체는 약관에 공개된 값이라 가릴 것이 없다.
만들기·고치기는 그대로 ADMIN 전용이다.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import Role
from app.models.staff.branch import Branch
from app.schemas.base import CamelModel
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


class SurveyLinkOut(CamelModel):
    branch_name: str
    url: str


@router.get("/{branch_id}/survey-link", response_model=SurveyLinkOut)
async def branch_survey_link(
    branch_id: str,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SurveyLinkOut:
    """매장에 붙일 회원 설문 QR 주소 — **MASTER·ADMIN 만**.

    토큰이 곧 그 지점 설문의 열쇠라, 전 직원에게 보이면 아무나 대신 낼 수 있다.
    토큰이 아직 없는 지점(마이그레이션 뒤에 생긴 곳)은 여기서 만들어 붙인다.
    """
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise _not_found()
    if not branch.survey_token:
        branch.survey_token = secrets.token_urlsafe(12)
        await db.commit()
        await db.refresh(branch)
    return SurveyLinkOut(
        branch_name=branch.name,
        url=f"{settings.public_base_url.rstrip('/')}/survey/{branch.survey_token}",
    )


@router.post("/{branch_id}/survey-link/reset", response_model=SurveyLinkOut)
async def reset_branch_survey_link(
    branch_id: str,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SurveyLinkOut:
    """설문 주소를 새로 발급한다 — **옛 QR 은 그 즉시 안 열린다.**

    토큰을 지점 id 가 아니라 따로 둔 이유가 이것이다. 주소가 새어 나가
    엉뚱한 설문이 쌓이면 여기서 갈아 끼우고 QR 만 다시 뽑아 붙이면 된다.
    """
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise _not_found()
    branch.survey_token = secrets.token_urlsafe(12)
    await db.commit()
    await db.refresh(branch)
    return SurveyLinkOut(
        branch_name=branch.name,
        url=f"{settings.public_base_url.rstrip('/')}/survey/{branch.survey_token}",
    )


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
