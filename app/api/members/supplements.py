"""Supplement 라우터 — 영양제 권유 (회원 상세 §3.4 옆칸).

권한은 **운동일지와 똑같다** — 읽기는 그 회원을 볼 수 있는 직원이면 되고,
쓰기는 담당 트레이너 본인뿐이다. 영양제는 몸에 넣는 것을 권하는 자리라
누가 권했는지가 흐려지면 안 된다.

회원 쪽(공개 주소)에서는 **읽기만** 한다 — `app/api/public/training.py`.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user
from app.db.session import get_db
from app.models.members.member import Member
from app.models.members.supplement import Supplement
from app.models.staff.employee import Employee
from app.schemas.members.supplement import (
    MAX_SUPPLEMENTS,
    SupplementCreate,
    SupplementOut,
    SupplementUpdate,
)

router = APIRouter(
    prefix="/supplements", tags=["supplements"], dependencies=[Depends(get_current_user)]
)


def _not_found() -> HTTPException:
    return HTTPException(
        404, detail={"code": "SUPPLEMENT_NOT_FOUND", "message": "영양제를 찾을 수 없습니다"}
    )


async def _visible_member(db: AsyncSession, member_id: str, scope: str | None) -> Member:
    """볼 수 있는 회원만 — 남의 지점 회원은 있다는 사실도 숨긴다(404)."""
    member = await db.get(Member, member_id)
    if member is None or (scope and member.branch_id != scope):
        raise HTTPException(
            404, detail={"code": "MEMBER_NOT_FOUND", "message": "회원을 찾을 수 없습니다"}
        )
    return member


def _ensure_can_write(member: Member, current: Employee) -> None:
    """담당 트레이너 본인만 — 운동일지(`workouts._ensure_can_write`)와 같은 줄이다."""
    if member.owner_trainer_id == current.id:
        return
    raise HTTPException(
        403, detail={"code": "NOT_MY_MEMBER", "message": "담당 트레이너만 영양제를 적을 수 있습니다"}
    )


def _ordered(member_id: str):
    """차례 → 만든 순. `sort_order` 가 같으면(옛 줄) 적은 차례로 선다."""
    return (
        select(Supplement)
        .where(Supplement.member_id == member_id)
        .order_by(Supplement.sort_order, Supplement.created_at)
    )


@router.get("", response_model=list[SupplementOut])
async def list_supplements(
    member_id: str = Query(..., alias="memberId"),
    scope: str | None = Depends(branch_scope),
    db: AsyncSession = Depends(get_db),
) -> list[Supplement]:
    await _visible_member(db, member_id, scope)
    result = await db.execute(_ordered(member_id))
    return list(result.scalars().all())


@router.post("", response_model=SupplementOut, status_code=201)
async def create_supplement(
    payload: SupplementCreate,
    current: Employee = Depends(get_current_user),
    scope: str | None = Depends(branch_scope),
    db: AsyncSession = Depends(get_db),
) -> Supplement:
    member = await _visible_member(db, payload.member_id, scope)
    _ensure_can_write(member, current)

    count = await db.scalar(
        select(func.count()).select_from(Supplement).where(Supplement.member_id == member.id)
    )
    if int(count or 0) >= MAX_SUPPLEMENTS:
        raise HTTPException(
            400,
            detail={
                "code": "TOO_MANY_SUPPLEMENTS",
                "message": f"영양제는 {MAX_SUPPLEMENTS}개까지 담을 수 있어요",
            },
        )

    last = await db.scalar(
        select(func.coalesce(func.max(Supplement.sort_order), -1)).where(
            Supplement.member_id == member.id
        )
    )
    row = Supplement(
        member_id=member.id,
        name=payload.name.strip(),
        dose=payload.dose.strip(),
        timing=payload.timing.strip(),
        reason=payload.reason.strip(),
        note=payload.note.strip(),
        sort_order=int(last) + 1,
        author_id=current.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.patch("/{supplement_id}", response_model=SupplementOut)
async def update_supplement(
    supplement_id: str,
    payload: SupplementUpdate,
    current: Employee = Depends(get_current_user),
    scope: str | None = Depends(branch_scope),
    db: AsyncSession = Depends(get_db),
) -> Supplement:
    row = await db.get(Supplement, supplement_id)
    if row is None:
        raise _not_found()
    member = await _visible_member(db, row.member_id, scope)
    _ensure_can_write(member, current)

    for key, value in payload.model_dump(exclude_unset=True).items():
        # `None` 은 "비우라" 가 아니라 "안 보냈다" 는 뜻이다
        if value is None:
            continue
        setattr(row, key, value.strip())
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{supplement_id}", status_code=204)
async def delete_supplement(
    supplement_id: str,
    current: Employee = Depends(get_current_user),
    scope: str | None = Depends(branch_scope),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await db.get(Supplement, supplement_id)
    if row is None:
        raise _not_found()
    member = await _visible_member(db, row.member_id, scope)
    _ensure_can_write(member, current)
    await db.delete(row)
    await db.commit()
