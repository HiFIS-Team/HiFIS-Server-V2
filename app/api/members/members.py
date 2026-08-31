"""Member 라우터 — CLAUDE.md §3.1.

문서 권한 [MEMBER,MANAGER] + ADMIN 오버사이트 → 인증된 직원이면 접근.
목록은 지점 스코프(§0): MEMBER=본인 지점 / MANAGER·ADMIN=전체.
"""

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_filter, branch_scope, get_current_user
from app.core.tokens import TRAINING_TOKEN_LENGTH, public_token
from app.db.session import get_db
from app.enums import VISIT_PATH_SCORE, Role
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.models.legal.consent import MemberConsent
from app.models.members.member import Member
from app.models.members.pt_survey import PtSurvey
from app.models.members.registration import Registration
from app.models.members.session_sign import SessionSign
from app.models.members.workout import WorkoutLog
from app.models.scoring.score_event import ScoreEvent
from app.schemas.members.member import MemberCreate, MemberCreateOut, MemberOut, MemberUpdate
from app.schemas.members.registration import RegistrationOut
from app.services.registrations import accrue_sales_score, counts_now, ensure_used_within, initial_status
from app.services.scoring import accrue_score

logger = logging.getLogger(__name__)

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


def _ensure_mine(member: Member, current: Employee) -> None:
    """고치거나 지울 수 있는 사람인가 — **담당 트레이너 본인 · MASTER · ADMIN**.

    앱의 `_canWrite`(회원 상세)와 **같은 규칙**이다. 갈리면 눌러도 403 이 나는
    버튼이 생기거나, 화면에 없는 일을 API 로는 할 수 있게 된다.

    점장을 안 넣은 이유 — 점장이 등록한 회원은 본인이 담당이라 여기에 든다.
    남의 담당 회원까지 손대는 것은 요청에 없었다 (2026-08-31).
    """
    if current.role in (Role.MASTER, Role.ADMIN):
        return
    if member.owner_trainer_id == current.id:
        return
    raise HTTPException(
        403, detail={"code": "NOT_MY_MEMBER", "message": "담당 회원만 고칠 수 있습니다"}
    )


def _drop_file(url: str | None) -> None:
    """올라간 파일 하나를 지운다 — 서명 이미지·운동 사진.

    행만 지우면 **개인정보가 디스크에 남는다** (동의 서명·운동 사진).
    문서함 삭제와 같은 방식이다.
    """
    if not url:
        return
    path = url.split("?", 1)[0].lstrip("/")
    if path.startswith("uploads/") and os.path.exists(path):
        os.remove(path)


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "MEMBER_NOT_FOUND", "message": "회원을 찾을 수 없습니다"})


@router.get("", response_model=list[MemberOut])
async def list_members(
    db: AsyncSession = Depends(get_db),
    # **MANAGER 는 고정이다.** 이 화면이 보여주는 건 '내가 담당하는 회원'
    # (`myMembers`)이라 다른 지점을 골라 봐야 0명이다. 회원 등록의 소개 회원
    # 고르개도 이 목록을 쓰는데, 거기까지 전사로 열 이유가 없다.
    scope: str | None = Depends(branch_filter),
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
        training_token=public_token(TRAINING_TOKEN_LENGTH),
    )
    db.add(member)
    await db.flush()  # member.id 확보

    # 방문 경로 점수 — 블로그·인스타·OT→PT 만 담당 트레이너에게 5점.
    #
    # **신규 등록에만 준다.** 재등록(`POST /registrations`)에는 안 붙는다 —
    # 방문 경로는 처음 올 때의 이야기라 재등록마다 또 주면 같은 유입으로
    # 점수가 계속 쌓인다.
    #
    # **지난 달 결제(기존 회원)에도 안 준다 (2026-08-21).** 앱을 켜기 전에
    # 등록했던 사람을 뒤늦게 넣는 것이라, 오늘 점수를 주면 지난 유입이
    # 이번 달 랭킹으로 들어온다. 매출을 `purchased_at` 으로 거르는 것과
    # 같은 기준이다 (`services/registrations.counts_now`).
    awarded = VISIT_PATH_SCORE.get(payload.visit_path) if payload.visit_path else None
    if awarded is not None and not counts_now(reg_in.purchased_at if reg_in else None):
        awarded = None
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
        # 기존 회원은 **이미 받은 회차**가 있다 — 안 받으면 남은 회차가 틀리고
        # 세션 싸인을 1회차부터 다시 받는다 (안 보내면 0 이라 옛 앱은 그대로다)
        ensure_used_within(reg_in.used_sessions, reg_in.total_sessions)
        registration = Registration(
            member_id=member.id,
            trainer_id=reg_trainer.id,
            type=reg_in.type,
            total_sessions=reg_in.total_sessions,
            used_sessions=reg_in.used_sessions,
            price_paid=reg_in.price_paid,
            session_unit_price=reg_in.session_unit_price,
            status=initial_status(reg_in.used_sessions, reg_in.total_sessions),
            purchased_at=reg_in.purchased_at or datetime.now(timezone.utc),
        )
        db.add(registration)
        await db.flush()
        await accrue_sales_score(db, registration, reg_trainer)

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
    # **담당 트레이너 본인이거나 대표·관리자만.** 예전에는 인증만 되면 아무나
    # 남의 지점 회원 이름을 고칠 수 있었다 (2026-08-31 에 닫았다)
    _ensure_mine(member, current)
    data = payload.model_dump(exclude_unset=True)
    # 담당 트레이너 재배정은 매출 귀속이 바뀌므로 ADMIN·MANAGER 만(매출 가로채기 차단)
    if (
        "owner_trainer_id" in data
        and data["owner_trainer_id"] != member.owner_trainer_id
        and current.role not in (Role.MASTER, Role.ADMIN, Role.MANAGER)
    ):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "담당 트레이너 변경은 관리자/매니저만 가능합니다"})
    await _validate_refs(db, None, data.get("owner_trainer_id"), data.get("referrer_member_id"))
    # 빈 줄은 버린다 — 앱이 '추가' 로 만들어 두고 안 채운 칸이 그대로 온다.
    # null 로 와도 빈 목록이다 (이 칸은 NOT NULL 이라 None 을 넣으면 터진다)
    if "goals" in data:
        data["goals"] = [line.strip() for line in (data["goals"] or []) if line.strip()]
    for key, value in data.items():
        setattr(member, key, value)
    await db.commit()
    await db.refresh(member)
    return member


@router.delete("/{member_id}", status_code=204)
async def delete_member(
    member_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """회원을 지운다 — **담당 트레이너 본인 · MASTER · ADMIN** (2026-08-31 대표 요청).

    예전에는 지우는 길이 아예 없어서 잘못 만든 회원을 대표가 손으로 치웠다.
    운영에 **같은 사람이 두 줄**로 들어간 것이 여럿이고(`안계옥님` · `안계옥`),
    그 결제액이 매출 랭킹에 두 번 잡히고 있었다.

    ## 정말로 지운다 — 감추는 것이 아니다

    행을 남겨 두고 목록에서만 빼면 **결제액이 랭킹·대시보드에 그대로 남아서**
    중복이 안 풀린다. 그러면 지우는 뜻이 없다. 그래서 딸린 것을 다 걷는다.

    | 걷는 것 | 왜 |
    |---|---|
    | 등록권 · 세션 싸인 · 운동일지 · PT 만족도 · 동의 | 그 회원만의 기록이다 |
    | 점수 원장 — 매출 · 수업 · 회원 등록 유입 | 안 걷으면 랭킹에 점수만 남는다 |
    | 서명 이미지 · 운동 사진 | 행만 지우면 개인정보가 디스크에 남는다 |
    | 이 사람을 소개자로 적은 회원 | 그 칸만 비운다 (그 회원은 그대로다) |

    **이미 지급된 급여는 안 바뀐다** — 명세서는 만들 때 값을 찍어 둔 행이라
    나중에 다시 세지 않는다. 아직 안 닫힌 달의 인센티브는 줄어든다(그게 맞다 —
    없던 회원의 수업이었다).

    **되돌릴 수 없다.** 앱이 누르기 전에 한 번 묻고, 활동 기록에 누가 무엇을
    지웠는지 남는다.
    """
    member = await db.get(Member, member_id)
    if member is None:
        raise _not_found()
    _ensure_mine(member, current)

    regs = list(await db.scalars(select(Registration).where(Registration.member_id == member_id)))
    signs = list(await db.scalars(select(SessionSign).where(SessionSign.member_id == member_id)))
    logs = list(await db.scalars(select(WorkoutLog).where(WorkoutLog.member_id == member_id)))
    consents = list(await db.scalars(select(MemberConsent).where(MemberConsent.member_id == member_id)))

    # 점수 원장 — 세 갈래가 이 회원에게서 나왔다. `source_ref_id` 로 되짚는다
    refs = [member.id, *(f"sales:{r.id}" for r in regs), *(s.id for s in signs)]
    await db.execute(delete(ScoreEvent).where(ScoreEvent.source_ref_id.in_(refs)))

    # 소개자로 걸린 회원은 그 칸만 비운다 — 외래키가 걸려 있고, 소개받은
    # 사람까지 같이 지울 이유는 없다
    await db.execute(
        update(Member).where(Member.referrer_member_id == member_id).values(referrer_member_id=None)
    )

    for sign in signs:
        _drop_file(sign.signature_url)
    for consent in consents:
        _drop_file(consent.signature_url)
    for log in logs:
        for group in log.media or []:
            for item in (group or {}).get("items", []):
                _drop_file((item or {}).get("url"))

    await db.execute(delete(PtSurvey).where(PtSurvey.member_id == member_id))
    await db.execute(delete(MemberConsent).where(MemberConsent.member_id == member_id))
    await db.execute(delete(WorkoutLog).where(WorkoutLog.member_id == member_id))
    await db.execute(delete(SessionSign).where(SessionSign.member_id == member_id))
    await db.execute(delete(Registration).where(Registration.member_id == member_id))
    await db.delete(member)
    await db.commit()
    logger.info(
        "회원 삭제: %s(%s) — 등록권 %d · 싸인 %d · 일지 %d · 지운 사람 %s",
        member.name, member_id, len(regs), len(signs), len(logs), current.name,
    )
    return Response(status_code=204)


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
