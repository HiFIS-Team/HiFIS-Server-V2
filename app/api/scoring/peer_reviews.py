"""PeerReview 라우터 — 동료평가 (CLAUDE.md §4.3).

POST [MEMBER]: 별점 제출 → total 계산 → reviewee 에게 PEER 점수 적립, 제출 후 잠김.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import Role, ScoreCategory
from app.models.staff.employee import Employee
from app.models.scoring.peer_review import PeerReview
from app.schemas.scoring.peer_review import (
    PeerAggregateItem,
    PeerReviewCreate,
    PeerReviewOut,
    PeerScores,
    PeerWindowOut,
)
from app.services.peer_reviews import (
    latest_period,
    missing_targets,
    open_period,
    review_targets,
)
from app.services.scoring import accrue_score

router = APIRouter(prefix="/peer-reviews", tags=["peer-reviews"])

STAR_KEYS = ("competency", "collaboration", "contribution", "attitude", "leadership")


def _compute_total(scores: PeerScores, is_self: bool) -> int:
    total = sum(getattr(scores, key) for key in STAR_KEYS)  # 별점 합 (5~25)
    return total * (1 if is_self else 4)  # 별×4(상대)/별×1(자기) → 전체 최대 100/25


def _to_out(review: PeerReview) -> PeerReviewOut:
    return PeerReviewOut(
        id=review.id,
        reviewer_id=review.reviewer_id,
        reviewee_id=review.reviewee_id,
        is_self=review.is_self,
        period=review.period,
        scores=PeerScores(
            competency=review.competency,
            collaboration=review.collaboration,
            contribution=review.contribution,
            attitude=review.attitude,
            leadership=review.leadership,
        ),
        reasons=review.reasons,
        total=review.total,
        submitted_at=review.submitted_at,
    )


@router.post("", response_model=PeerReviewOut, status_code=201)
async def create_peer_review(
    payload: PeerReviewCreate,
    # 점장(MANAGER)도 동료평가에 참여함 → 허용. ADMIN·MASTER 는 운영 전담이라 제외.
    current: Employee = Depends(require_role(Role.MEMBER, Role.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> PeerReviewOut:
    # 평가 창은 **말일과 다음달 1일 이틀뿐**이다 (2026-08-31 대표 결정).
    # 앱도 그때만 열어 주지만, 막는 것은 여기가 마지막 자리다.
    period = open_period()
    if period is None:
        raise HTTPException(
            400,
            detail={"code": "NOT_REVIEW_PERIOD", "message": "동료평가는 매월 말일과 다음달 1일에만 낼 수 있습니다"},
        )
    # 두 날이 같은 달을 평가한다 — 9/1 에 내는 것은 9월이 아니라 8월 것이다.
    # 앱이 딴 값을 보내면 여기서 바로잡는다 (안 그러면 한 창이 두 기간으로 갈린다)
    payload.period = period

    reviewee = await db.get(Employee, payload.reviewee_id)
    if reviewee is None:
        raise HTTPException(400, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "평가 대상이 존재하지 않습니다"})

    missing = [key for key in STAR_KEYS if not payload.reasons.get(key, "").strip()]
    if missing:
        raise HTTPException(400, detail={"code": "REASON_REQUIRED", "message": f"사유 필수 항목: {missing}"})

    is_self = current.id == payload.reviewee_id
    duplicate = await db.execute(
        select(PeerReview).where(
            PeerReview.reviewer_id == current.id,
            PeerReview.reviewee_id == payload.reviewee_id,
            PeerReview.period == payload.period,
        )
    )
    if duplicate.scalar_one_or_none():
        raise HTTPException(409, detail={"code": "ALREADY_SUBMITTED", "message": "이미 제출한 평가입니다 (수정 불가)"})

    total = _compute_total(payload.scores, is_self)
    review = PeerReview(
        reviewer_id=current.id,
        reviewee_id=payload.reviewee_id,
        is_self=is_self,
        period=payload.period,
        competency=payload.scores.competency,
        collaboration=payload.scores.collaboration,
        contribution=payload.scores.contribution,
        attitude=payload.scores.attitude,
        leadership=payload.scores.leadership,
        reasons=payload.reasons,
        total=total,
    )
    db.add(review)
    await db.flush()
    await accrue_score(
        db,
        employee_id=payload.reviewee_id,
        branch_id=reviewee.branch_id,
        category=ScoreCategory.PEER,
        points=total,
        # **평가자를 안 남긴다** (2026-08-31 대표 지시 — 익명이 이 기능의 전제다).
        #
        # 예전에는 `created_by_id=current.id` 였다. 그런데 `GET /scores` 는
        # 사람을 안 가려서, **평가받은 사람이 자기 PEER 점수 줄에서 누가
        # 평가했는지 그대로 봤다** (점수로 별점까지 역산된다). 실제로 재 봤다 —
        # `+76점 createdById=권나연`.
        #
        # 누가 썼는지는 `peer_reviews.reviewer_id` 에 그대로 남는다. 그 표는
        # MEMBER·MANAGER 에게 **본인이 쓴 것만** 보이므로(익명성 보호, §33)
        # 면담 자료로는 여전히 ADMIN·MASTER 가 볼 수 있다.
        created_by_id=None,
        source_ref_id=review.id,
        period=payload.period,
        reason="동료평가",
    )
    await db.commit()
    await db.refresh(review)
    return _to_out(review)


@router.get("/window", response_model=PeerWindowOut)
async def peer_review_window(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PeerWindowOut:
    """지금 평가를 쓸 수 있는지 + 내가 몇 명 남았는지.

    앱이 이걸로 **안내 줄**(기간이 아닐 때)과 **재촉 모달**(안 낸 사람에게)을
    정한다. 권한 없이 본인 것만 본다.
    """
    # 닫혀 있어도 **기간은 준다** — 지난 창에 낸 평가를 읽어야 하고,
    # 앱에 날짜 계산을 두면 서버와 갈릴 자리가 하나 더 생긴다
    period = latest_period()
    targets = await review_targets(db, current)
    missing = await missing_targets(db, current, period)
    return PeerWindowOut(
        is_open=open_period() is not None,
        period=period,
        total=len(targets),
        remaining=len(missing),
    )


@router.get("/aggregate", response_model=list[PeerAggregateItem], dependencies=[Depends(require_role(Role.ADMIN))])
async def aggregate_peer_reviews(
    db: AsyncSession = Depends(get_db), period: str | None = Query(None)
) -> list[PeerAggregateItem]:
    category_sums = [func.coalesce(func.sum(getattr(PeerReview, key)), 0) for key in STAR_KEYS]
    stmt = select(
        Employee.id,
        Employee.name,
        func.count(PeerReview.id),
        func.coalesce(func.sum(PeerReview.total), 0),
        *category_sums,
    ).join(PeerReview, PeerReview.reviewee_id == Employee.id)
    if period:
        stmt = stmt.where(PeerReview.period == period)
    stmt = stmt.group_by(Employee.id, Employee.name).order_by(func.sum(PeerReview.total).desc())
    rows = (await db.execute(stmt)).all()
    return [
        PeerAggregateItem(
            reviewee_id=row[0],
            name=row[1],
            review_count=row[2],
            total=row[3],
            by_category={STAR_KEYS[i]: row[4 + i] for i in range(len(STAR_KEYS))},
        )
        for row in rows
    ]


@router.get("", response_model=list[PeerReviewOut])
async def list_peer_reviews(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    reviewee_id: str | None = Query(None, alias="revieweeId"),
    period: str | None = Query(None),
) -> list[PeerReviewOut]:
    stmt = select(PeerReview)
    # 익명성 보호 — MEMBER·MANAGER 는 본인이 작성한 평가만(남의 평가·리뷰어 노출 차단).
    # 제출 현황(남이 쓴 평가)은 면담 자료라 ADMIN·MASTER 만 전체 열람. 점장(MANAGER)도 못 봄.
    if current.role in (Role.MEMBER, Role.MANAGER):
        stmt = stmt.where(PeerReview.reviewer_id == current.id)
    if reviewee_id:
        stmt = stmt.where(PeerReview.reviewee_id == reviewee_id)
    if period:
        stmt = stmt.where(PeerReview.period == period)
    result = await db.execute(stmt.order_by(PeerReview.submitted_at.desc()))
    return [_to_out(review) for review in result.scalars().all()]
