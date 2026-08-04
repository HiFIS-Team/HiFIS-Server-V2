"""회원 친절도 — 외부 웹훅 수신 + 조회 (CLAUDE.md §4.5).

POST /webhooks/kindness-survey: 앱 UI 작성 없음, 외부 폼 전용. 시크릿 검증 후 KINDNESS +10.
"""

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import branch_scope, get_current_user
from app.core.ratelimit import limiter
from app.db.session import get_db
from app.enums import ComplaintStatus, ScoreCategory
from app.models.staff.employee import Employee
from app.models.scoring.kindness import KindnessSurvey
from app.schemas.scoring.kindness import (
    ComplaintStatusUpdate,
    KindnessSurveyOut,
    KindnessSurveyWebhook,
)
from app.services.scoring import accrue_score

KINDNESS_POINTS = 10

router = APIRouter(tags=["kindness"])


async def _verify_webhook_secret(x_webhook_secret: str | None = Header(None)) -> None:
    if x_webhook_secret is None or not hmac.compare_digest(
        x_webhook_secret, settings.kindness_webhook_secret
    ):
        raise HTTPException(401, detail={"code": "INVALID_WEBHOOK_SECRET", "message": "웹훅 시크릿이 올바르지 않습니다"})


@router.post(
    "/webhooks/kindness-survey",
    response_model=KindnessSurveyOut,
    status_code=201,
    dependencies=[Depends(_verify_webhook_secret)],
)
@limiter.limit("30/minute")  # IP당 분 30회 — 웹훅 스팸/포인트 남용 방지(§M4)
async def receive_kindness_survey(
    request: Request, payload: KindnessSurveyWebhook, db: AsyncSession = Depends(get_db)
) -> KindnessSurvey:
    if not payload.consent:
        raise HTTPException(400, detail={"code": "CONSENT_REQUIRED", "message": "개인정보 동의가 필요합니다"})
    employee = await db.get(Employee, payload.praised_employee_id)
    if employee is None:
        raise HTTPException(400, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "칭찬 대상 직원이 존재하지 않습니다"})

    survey = KindnessSurvey(
        motivation=payload.motivation,
        praised_employee_id=payload.praised_employee_id,
        praise_comment=payload.praise_comment,
        improvement=payload.improvement,
        member_name=payload.member_name,
        member_phone=payload.member_phone,
        consent=True,
    )
    db.add(survey)
    await db.flush()
    await accrue_score(
        db,
        employee_id=payload.praised_employee_id,
        branch_id=employee.branch_id,
        category=ScoreCategory.KINDNESS,
        points=KINDNESS_POINTS,
        source_ref_id=survey.id,
        reason="회원 친절도 칭찬",
    )
    await db.commit()
    await db.refresh(survey)
    return survey


@router.get("/kindness-surveys", response_model=list[KindnessSurveyOut], dependencies=[Depends(get_current_user)])
async def list_kindness_surveys(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    praised_employee_id: str | None = Query(None, alias="praisedEmployeeId"),
) -> list[KindnessSurvey]:
    stmt = select(KindnessSurvey)
    if scope:
        stmt = stmt.join(Employee, Employee.id == KindnessSurvey.praised_employee_id).where(
            Employee.branch_id == scope
        )
    if praised_employee_id:
        stmt = stmt.where(KindnessSurvey.praised_employee_id == praised_employee_id)
    result = await db.execute(stmt.order_by(KindnessSurvey.submitted_at.desc()))
    return list(result.scalars().all())


@router.patch("/kindness-surveys/{survey_id}/status", response_model=KindnessSurveyOut)
async def set_complaint_status(
    survey_id: str,
    payload: ComplaintStatusUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KindnessSurvey:
    """컴플레인 처리 단계 바꾸기 — 미처리 → 해결중 → 해결 완료.

    **누구나 바꿀 수 있다.** 컴플레인은 매장 전체의 일이라 고친 사람이
    표시하면 된다. 다만 누가 언제 끝냈는지는 남긴다.

    개선 의견이 없는 설문(칭찬만 있는 것)은 컴플레인이 아니라서 막는다.
    """
    survey = await db.get(KindnessSurvey, survey_id)
    if survey is None:
        raise HTTPException(404, detail={"code": "SURVEY_NOT_FOUND", "message": "설문을 찾을 수 없습니다"})
    if not (survey.improvement or "").strip():
        raise HTTPException(
            400, detail={"code": "NOT_A_COMPLAINT", "message": "개선 의견이 없는 설문입니다"}
        )

    survey.improvement_status = payload.status
    if payload.status == ComplaintStatus.DONE:
        survey.resolved_at = datetime.now(timezone.utc)
        survey.resolved_by_id = current.id
    else:
        # 되돌리면 해결 기록도 지운다 — 안 지우면 TV에 '해결 완료' 로 남는다
        survey.resolved_at = None
        survey.resolved_by_id = None
    await db.commit()
    await db.refresh(survey)
    return survey
