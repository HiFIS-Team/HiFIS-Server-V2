"""Member 라우터 — CLAUDE.md §3.1.

문서 권한 [MEMBER,MANAGER] + ADMIN 오버사이트 → 인증된 직원이면 접근.
목록은 지점 스코프(§0): MEMBER=본인 지점 / MANAGER·ADMIN=전체.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_pick, branch_scope, get_current_user
from app.db.session import get_db
from app.enums import VISIT_PATH_SCORE, RegistrationStatus, Role
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.models.members.member import Member
from app.models.members.registration import Registration
from app.schemas.members.member import MemberCreate, MemberCreateOut, MemberOut, MemberUpdate
from app.schemas.members.registration import RegistrationOut
from app.services.scoring import accrue_score

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
    scope: str | None = Depends(branch_pick),  # 업무 화면(수업 개수) — MANAGER 도 고른다
    owner_trainer_id: str | None = Query(None, alias="ownerTrainerId"),
    q: str | None = Query(None),
) -> list[Member]:
    stmt = select(Member)
    if scope:
        stmt = stmt.where(Member.branch_id == scope)
    if owner_trainer_id:
        stmt = stmt.where(Member.owner_trainer_id == owner_trainer_id)
    if q:
        stmt = stmt.where(Member.name.ilike(f"%{q}%"))
    result = await db.execute(stmt.order_by(Member.registered_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=MemberCreateOut, status_code=201)
async def create_member(
    payload: MemberCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemberCreateOut:
    await _validate_refs(db, payload.branch_id, payload.owner_trainer_id, payload.referrer_member_id)

    # 첫 등록권 동봉 시 — 회원 생성 전에 트레이너·권한부터 검증(실패해도 회원이 남지 않게)
    reg_in = payload.registration
    reg_trainer: Employee | None = None
    if reg_in is not None:
        trainer_id = reg_in.trainer_id or payload.owner_trainer_id
        reg_trainer = await db.get(Employee, trainer_id)
        if reg_trainer is None:
            raise HTTPException(400, detail={"code": "TRAINER_NOT_FOUND", "message": "트레이너가 존재하지 않습니다"})
        # 급여 조작 방지 — /registrations 와 동일 규칙(MEMBER=본인 담당만·크로스브랜치 차단)
        if current.role == Role.MEMBER and trainer_id != current.id:
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 담당 등록만 생성할 수 있습니다"})
        if current.role not in (Role.MASTER, Role.ADMIN) and reg_trainer.branch_id != current.branch_id:
            raise HTTPException(403, detail={"code": "OTHER_BRANCH", "message": "다른 지점 등록은 생성할 수 없습니다"})

    member = Member(
        name=payload.name,
        phone=payload.phone,
        branch_id=payload.branch_id,
        owner_trainer_id=payload.owner_trainer_id,
        referrer_member_id=payload.referrer_member_id,
        visit_path=payload.visit_path,
        memo=payload.memo,
    )
    db.add(member)
    await db.flush()  # member.id 확보

    # 방문 경로 점수 — 블로그·인스타·OT→PT 만 담당 트레이너에게 5점.
    #
    # **신규 등록에만 준다.** 재등록(`POST /registrations`)에는 안 붙는다 —
    # 방문 경로는 처음 올 때의 이야기라 재등록마다 또 주면 같은 유입으로
    # 점수가 계속 쌓인다.
    awarded = VISIT_PATH_SCORE.get(payload.visit_path) if payload.visit_path else None
    if awarded is not None:
        category, points = awarded
        owner = await db.get(Employee, payload.owner_trainer_id)
        await accrue_score(
            db,
            employee_id=payload.owner_trainer_id,
            # 점수는 **그 사람 소속 지점**에 쌓는다. 회원 지점을 쓰면 다른
            # 지점 회원을 등록했을 때 남의 지점 랭킹에 들어간다.
            branch_id=owner.branch_id if owner else payload.branch_id,
            category=category,
            points=points,
            created_by_id=current.id,
            source_ref_id=member.id,
            reason="회원 등록 유입",
        )

    registration: Registration | None = None
    if reg_in is not None:
        registration = Registration(
            member_id=member.id,
            trainer_id=reg_trainer.id,
            type=reg_in.type,
            total_sessions=reg_in.total_sessions,
            used_sessions=0,
            price_paid=reg_in.price_paid,
            session_unit_price=reg_in.session_unit_price,
            status=RegistrationStatus.ACTIVE,
            purchased_at=reg_in.purchased_at or datetime.now(timezone.utc),
        )
        db.add(registration)

    await db.commit()
    await db.refresh(member)
    out = MemberCreateOut.model_validate(member)
    if registration is not None:
        await db.refresh(registration)
        out.registration = RegistrationOut.model_validate(registration)
    return out


@router.get("/{member_id}", response_model=MemberOut)
async def get_member(
    member_id: str,
    scope: str | None = Depends(branch_scope),
    db: AsyncSession = Depends(get_db),
) -> Member:
    member = await db.get(Member, member_id)
    if member is None or (scope and member.branch_id != scope):  # 타 지점 회원 존재도 숨김(404)
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
        and current.role not in (Role.MASTER, Role.ADMIN, Role.MANAGER)
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
    member_id: str,
    scope: str | None = Depends(branch_scope),
    db: AsyncSession = Depends(get_db),
) -> list[Registration]:
    member = await db.get(Member, member_id)
    if member is None or (scope and member.branch_id != scope):
        raise _not_found()
    result = await db.execute(
        select(Registration)
        .where(Registration.member_id == member_id)
        .order_by(Registration.purchased_at.desc())
    )
    return list(result.scalars().all())
