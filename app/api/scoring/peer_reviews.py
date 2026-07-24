"""PeerReview 라우터 — 동료평가 (CLAUDE.md §4.3).

POST [MEMBER]: 별점 제출 → total 계산 → reviewee 에게 PEER 점수 적립, 제출 후 잠김.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user, require_role
from app.db.session import get_db
from app.enums import Role, ScoreCategory
from app.models.staff.employee import Employee
from app.models.scoring.peer_review import PeerReview
from app.schemas.scoring.peer_review import (
    PeerAggregateItem,
    PeerReviewCreate,
    PeerReviewOut,
    PeerScores,
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
    current: Employee = Depends(require_role(Role.MEMBER)),
    db: AsyncSession = Depends(get_db),
) -> PeerReviewOut:
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
        created_by_id=current.id,
        source_ref_id=review.id,
        period=payload.period,
        reason="동료평가",
    )
    await db.commit()
    await db.refresh(review)
    return _to_out(review)


@router.get("/aggregate", response_model=list[PeerAggregateItem], dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
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
    scope: str | None = Depends(branch_scope),
    reviewee_id: str | None = Query(None, alias="revieweeId"),
    period: str | None = Query(None),
) -> list[PeerReviewOut]:
    stmt = select(PeerReview)
    # 멤버는 본인이 작성한 평가만(익명성 보호) — 남의 평가·리뷰어 노출 차단. MANAGER·ADMIN 은 전체.
    if current.role == Role.MEMBER:
        stmt = stmt.where(PeerReview.reviewer_id == current.id)
    elif scope:
        stmt = stmt.join(Employee, Employee.id == PeerReview.reviewee_id).where(
            Employee.branch_id == scope
        )
    if reviewee_id:
        stmt = stmt.where(PeerReview.reviewee_id == reviewee_id)
    if period:
        stmt = stmt.where(PeerReview.period == period)
    result = await db.execute(stmt.order_by(PeerReview.submitted_at.desc()))
    return [_to_out(review) for review in result.scalars().all()]
