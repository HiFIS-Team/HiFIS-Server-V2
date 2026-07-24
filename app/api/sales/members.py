"""Member 라우터 — CLAUDE.md §3.1.

문서 권한 [MEMBER,MANAGER] + ADMIN 오버사이트 → 인증된 직원이면 접근.
목록은 지점 스코프(§0): MEMBER=본인 지점 / MANAGER·ADMIN=전체.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user
from app.db.session import get_db
from app.enums import Role
from app.models.org.branch import Branch
from app.models.org.employee import Employee
from app.models.sales.member import Member
from app.models.sales.registration import Registration
from app.schemas.sales.member import MemberCreate, MemberOut, MemberUpdate
from app.schemas.sales.registration import RegistrationOut

router = APIRouter(prefix="/members", tags=["members"], dependencies=[Depends(get_current_user)])


async def _validate_refs(
    db: AsyncSession, branch_id: str | None, owner_trainer_id: str | None, referrer_member_id: str | None
) -> None:
    if branch_id is not None and await db.get(Branch, branch_id) is None:
        raise HTTPException(400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"})
    if owner_trainer_id is not None and await db.get(Employee, owner_trainer_id) is None:
        raise HTTPException(400, detail={"code": "TRAINER_NOT_FOUND", "message": "담당 트레이너가 존재하지 않습니다"})
    if referrer_member_id is not None and await db.get(Member, referrer_member_id) is None:
        raise HTTPException(400, detail={"code": "REFERRER_NOT_FOUND", "message": "소개 회원이 존재하지 않습니다"})


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "MEMBER_NOT_FOUND", "message": "회원을 찾을 수 없습니다"})


@router.get("", response_model=list[MemberOut])
async def list_members(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    branch_id: str | None = Query(None, alias="branchId"),
    owner_trainer_id: str | None = Query(None, alias="ownerTrainerId"),
    q: str | None = Query(None),
) -> list[Member]:
    stmt = select(Member)
    if scope:
        stmt = stmt.where(Member.branch_id == scope)
    if branch_id:
        stmt = stmt.where(Member.branch_id == branch_id)
    if owner_trainer_id:
        stmt = stmt.where(Member.owner_trainer_id == owner_trainer_id)
    if q:
        stmt = stmt.where(Member.name.ilike(f"%{q}%"))
    result = await db.execute(stmt.order_by(Member.registered_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=MemberOut, status_code=201)
async def create_member(payload: MemberCreate, db: AsyncSession = Depends(get_db)) -> Member:
    await _validate_refs(db, payload.branch_id, payload.owner_trainer_id, payload.referrer_member_id)
    member = Member(
        name=payload.name,
        phone=payload.phone,
        branch_id=payload.branch_id,
        owner_trainer_id=payload.owner_trainer_id,
        referrer_member_id=payload.referrer_member_id,
        memo=payload.memo,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@router.get("/{member_id}", response_model=MemberOut)
async def get_member(member_id: str, db: AsyncSession = Depends(get_db)) -> Member:
    member = await db.get(Member, member_id)
    if member is None:
        raise _not_found()
    return member


@router.patch("/{member_id}", response_model=MemberOut)
async def update_member(
    member_id: str,
    payload: MemberUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Member:
    member = await db.get(Member, member_id)
    if member is None:
        raise _not_found()
    data = payload.model_dump(exclude_unset=True)
    # 담당 트레이너 재배정은 매출 귀속이 바뀌므로 ADMIN·MANAGER 만(매출 가로채기 차단)
    if (
        "owner_trainer_id" in data
        and data["owner_trainer_id"] != member.owner_trainer_id
        and current.role not in (Role.ADMIN, Role.MANAGER)
    ):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "담당 트레이너 변경은 관리자/매니저만 가능합니다"})
    await _validate_refs(db, None, data.get("owner_trainer_id"), data.get("referrer_member_id"))
    for key, value in data.items():
        setattr(member, key, value)
    await db.commit()
    await db.refresh(member)
    return member


@router.get("/{member_id}/registrations", response_model=list[RegistrationOut])
async def list_member_registrations(
    member_id: str, db: AsyncSession = Depends(get_db)
) -> list[Registration]:
    if await db.get(Member, member_id) is None:
        raise _not_found()
    result = await db.execute(
        select(Registration)
        .where(Registration.member_id == member_id)
        .order_by(Registration.purchased_at.desc())
    )
    return list(result.scalars().all())
